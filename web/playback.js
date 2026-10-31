// Public Spotify iFrame API and native previews share one playback lifecycle.
import { ensureTrackDetails, trackSummary } from './track-context.js';
import { playSpotifyExcerpt, stopSpotifyPlayback, setSpotifyFeedback, prepareSpotifyPlayback } from './spotify.js';
let spotifyAPI;
function loadSpotifyAPI() {
  if (spotifyAPI) return spotifyAPI;
  spotifyAPI = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Spotify indisponível.')), 18000);
    window.onSpotifyIframeApiReady = api => { clearTimeout(timeout); resolve(api); };
    const script = document.createElement('script'); script.src = 'https://open.spotify.com/embed/iframe-api/v1'; script.async = true;
    script.onerror = () => { clearTimeout(timeout); spotifyAPI = null; script.remove(); reject(new Error('Spotify indisponível.')); };
    document.head.append(script);
  });
  return spotifyAPI;
}
export function createPlayback({ tracks, musicDetails, toast }) {
  setSpotifyFeedback(toast);
  let audio = null, controller = null, generation = 0, coverButton = null, coverToggle = null;
  const playIcon = '<span aria-hidden="true">▶</span>';
  function state(button, playing) {
    if (!button?.isConnected) return;
    button.innerHTML = playing ? '<span aria-hidden="true">Ⅱ</span>' : playIcon;
    button.setAttribute('aria-pressed', String(playing));
    button.setAttribute('aria-label', `${playing ? 'Pausar' : 'Ouvir'} trecho`);
    button.classList.toggle('playing', playing);
  }
  function stopPreview() {
    stopSpotifyPlayback();
    document.dispatchEvent(new Event('ressoaplaybackstop'));
    generation++;
    coverButton=null;coverToggle=null;
    if (audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); audio = null; }
    try { controller?.pause(); controller?.destroy(); } catch {}
    controller = null;
    document.querySelectorAll('[data-preview-player]').forEach(host => host.replaceChildren());
    document.querySelectorAll('[data-play]').forEach(button => { state(button, false); button.removeAttribute('aria-busy'); });
    document.querySelector('#spotify-controller-host')?.replaceChildren();
  }
  function nativeAudio(detail, button, inline = false, index, excerpt = null) {
    const player = document.createElement('audio'); player.preload = 'none'; player.volume = .5;
    if (detail.previewUrl) player.src = detail.previewUrl;
    audio = player;
    const bounds=()=>({start:Math.min(excerpt?.start||0,Math.max(0,(player.duration||30)-1)),end:Math.min(excerpt?.end||30,player.duration||30)});
    player.addEventListener('loadedmetadata',()=>{if(excerpt)player.currentTime=bounds().start;});
    player.addEventListener('timeupdate',()=>{if(excerpt&&player.currentTime>=bounds().end-.04){player.pause();player.currentTime=bounds().start;}});
    const metadata=ensureTrackDetails(index).then(track=>{
      if(audio!==player)return;
      if(player.paused&&track?.previewUrl){const url=new URL(track.previewUrl);if(url.protocol==='https:'&&url.hostname.endsWith('.dzcdn.net'))player.src=url.href;}
      const caption=button.parentElement?.querySelector('.native-track-context');if(caption)caption.textContent=trackSummary(index);
    }).catch(()=>{});
    const toggle = async event => {
      event.stopPropagation();
      if (!player.src) { button.setAttribute('aria-busy','true');await metadata;button.removeAttribute('aria-busy'); }
      if(audio!==player)return;
      if (!player.src) { toast('Prévia indisponível para esta gravação.'); return; }
      try { if (player.paused) {if(excerpt&&(player.currentTime<bounds().start||player.currentTime>=bounds().end-.04))player.currentTime=bounds().start;await player.play();} else player.pause(); }
      catch { if (audio === player) toast('Não foi possível reproduzir o trecho.'); }
    };
    if(inline)button.onclick=toggle;else coverToggle=toggle;
    const sync = () => { if (inline) { button.setAttribute('aria-pressed', String(!player.paused)); button.textContent = player.paused ? '▶ Ouvir trecho' : 'Ⅱ Pausar trecho'; } else state(button, !player.paused); };
    player.addEventListener('play', sync); player.addEventListener('pause', sync); player.addEventListener('ended', sync);
    player.addEventListener('error', () => { if (audio === player) { state(button, false); toast('Prévia indisponível. Tente novamente.'); } });
    return player;
  }
  async function mountCoverPlayer(button, index, excerpt = null) {
    if (!button || !musicDetails[index]) return;
    stopPreview(); const token = generation; const detail = musicDetails[index];
    coverButton=button;
    state(button, false);
    if(detail.provider==='spotify'&&excerpt?.source==='spotify'){
      void prepareSpotifyPlayback().catch(()=>{});
      coverToggle=event=>{event.stopPropagation();button.setAttribute('aria-busy','true');void playSpotifyExcerpt(detail,excerpt,playing=>state(button,playing)).catch(error=>toast(error.message)).finally(()=>button.removeAttribute('aria-busy'));};
      return;
    }
    if (detail.provider !== 'spotify') { nativeAudio(detail, button, false, index, excerpt); return; }
    let ready = false, queued = false;
    coverToggle = event => {
      event.stopPropagation();
      if (token !== generation) return;
      if (ready) controller?.togglePlay(); else { queued = !queued; button.setAttribute('aria-busy', String(queued)); }
    };
    try {
      const api = await loadSpotifyAPI(); if (token !== generation) return;
      const dock = document.querySelector('#spotify-controller-host'); const element = document.createElement('div'); dock.replaceChildren(element);
      api.createController(element, { uri: `spotify:track:${detail.id}`, width: 300, height: 152 }, embed => {
        if (token !== generation) { embed.destroy(); return; }
        controller = embed;
        const frame = dock.querySelector('iframe');
        if (frame) { frame.tabIndex = -1; frame.loading = 'eager'; }
        embed.addListener('ready', () => { if (token !== generation) return; ready = true; button.removeAttribute('aria-busy'); if (queued) { queued = false; embed.play(); } });
        embed.addListener('playback_update', event => { if (token === generation) state(button, !event.data.isPaused); });
      });
    } catch {
      if (token === generation) { button.removeAttribute('aria-busy'); coverToggle = () => toast('O Spotify não carregou. Abra a ficha para tentar o player completo.'); }
    }
  }
  function toggleCoverPlayer(button,index,event,excerpt=null) {
    if(coverButton!==button)void mountCoverPlayer(button,index,excerpt);
    coverToggle?.(event);
  }
  function mountPreview(host, index, height = 152) {
    if (!host || !musicDetails[index]) return;
    stopPreview(); const detail = musicDetails[index];
    if (detail.provider === 'spotify') {
      const frame = document.createElement('iframe'); frame.title = `Spotify: ${tracks[index].title}`;
      frame.src = `https://open.spotify.com/embed/track/${detail.id}?utm_source=generator&theme=0`; frame.width = '100%'; frame.height = String(height);
      frame.allow = 'autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture'; frame.allowFullscreen = true; host.append(frame); return;
    }
    const box = document.createElement('div'); box.className = 'native-preview'; const button = document.createElement('button'); button.type = 'button'; button.className = 'preview-toggle'; button.textContent = '▶ Ouvir trecho'; button.setAttribute('aria-pressed','false'); box.append(button); host.append(box);
    const context=document.createElement('small');context.className='native-track-context';context.textContent=trackSummary(index);box.append(context);
    const player = nativeAudio(detail, button, true, index); box.append(player);
  }
  return { stopPreview, mountPreview, mountCoverPlayer, toggleCoverPlayer };
}

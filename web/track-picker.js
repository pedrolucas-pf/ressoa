import { tracks, musicDetails, registerTrack, sanitizeTrack } from './catalog-store.js';
const escape = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
import { trackSummary } from './track-context.js';
import { getSpotifyStatus, connectSpotify } from './spotify.js';
let pickerNumber = 0;

export function createTrackPicker(host, { onChange, onPreview, onStop, onError, label = 'Música' }) {
  const id = `track-picker-${++pickerNumber}`;
  host.innerHTML = `<label for="${id}">Música</label><div class="picker-sources" hidden><button type="button" data-catalog-source="deezer" aria-pressed="true">Prévias</button><button type="button" data-catalog-source="spotify" aria-pressed="false">Conectar Spotify</button></div><p class="form-note picker-source-note" hidden></p><div class="picker-search"><span aria-hidden="true">⌕</span><input id="${id}" class="catalog-query" type="search" placeholder="Música, artista ou link da faixa" autocomplete="off" spellcheck="false" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${id}-results"></div><p class="picker-status" role="status"></p><div class="catalog-results" id="${id}-results" role="listbox" aria-label="Resultados da busca" hidden></div><button type="button" class="text-button picker-more" hidden>Ver mais resultados</button><div class="selected-track" hidden></div>`;
  const input = host.querySelector('input');
  host.querySelector('label').textContent=label;
  const list = host.querySelector('.catalog-results');
  const status = host.querySelector('.picker-status');
  const selected = host.querySelector('.selected-track');
  const more=host.querySelector('.picker-more'),sources=host.querySelector('.picker-sources'),spotify=host.querySelector('[data-catalog-source="spotify"]'),sourceNote=host.querySelector('.picker-source-note');
  let results = [], current = null, highlighted = -1, timer, request, generation = 0,nextOffset=null,source='deezer',connected=false,manualSource=false;
  function collapse() { list.hidden = true;more.hidden=true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); highlighted = -1; }
  function cancel() { clearTimeout(timer); request?.abort(); generation++; input.removeAttribute('aria-busy'); }
  function clear(notify = true) {
    current = null; selected.replaceChildren(); selected.hidden = true; input.setCustomValidity('');
    onStop?.(); if (notify) onChange?.(null);
  }
  function setSelection(index, notify = true) {
    cancel(); collapse(); input.value = ''; input.setCustomValidity(''); status.textContent = '';
    if (!Number.isInteger(index) || !tracks[index]) { clear(notify); return; }
    current = index;
    const track = tracks[index], detail = musicDetails[index];
    selected.innerHTML = `<div class="selection-summary"><img src="${escape(detail.artwork || 'assets/cover-unavailable.svg')}" alt="" width="48" height="48"><div><strong>${escape(track.title)}</strong><span>${escape(track.artist)}${track.album ? ` · ${escape(track.album)}` : ''}</span></div><button type="button" class="icon-button clear-track" aria-label="Trocar música">×</button></div><div class="selection-player" data-preview-player></div>`;
    selected.hidden = false;
    selected.querySelector('.selection-summary span').textContent=[track.artist,trackSummary(index)].filter(Boolean).join(' · ');
    onPreview?.(selected.querySelector('[data-preview-player]'), index);
    if (notify) onChange?.(index);
  }
  async function choose(index) {
    try { setSelection(registerTrack(results[index])); }
    catch { onError?.('Não foi possível salvar a música neste navegador.'); }
  }
  function highlight(index) {
    highlighted = (index + results.length) % results.length;
    list.querySelectorAll('[role="option"]').forEach((option, i) => option.setAttribute('aria-selected', String(i === highlighted)));
    input.setAttribute('aria-activedescendant', `${id}-option-${highlighted}`);
    list.children[highlighted]?.scrollIntoView({ block: 'nearest' });
  }
  async function search(query,append=false) {
    cancel(); const token = generation; request = new AbortController();
    input.setAttribute('aria-busy', 'true'); status.textContent = 'Buscando…';more.disabled=true;if(!append)collapse();
    try {
      const response = await fetch(`/api/search?${new URLSearchParams({ q: query,provider:source,offset:append&&nextOffset!==null?nextOffset:0 })}`, { signal: request.signal });
      const data = await response.json();
      if (token !== generation) return;
      if (!response.ok) throw new Error(data.error || 'A busca está indisponível.');
      const found=(data.results || []).map(sanitizeTrack).filter(Boolean),unique=new Map((append?results:[]).map(track=>[track.catalogId,track]));found.forEach(track=>unique.set(track.catalogId,track));results=[...unique.values()];
      nextOffset=Number.isInteger(data.nextOffset)?data.nextOffset:null;
      status.textContent = results.length ? `${results.length} resultados · ${data.provider === 'spotify' ? 'Spotify' : 'Deezer'}` : 'Não encontrou? Tente o título com o artista ou cole o link da faixa.';
      list.innerHTML = results.map((track, i) => `<button type="button" role="option" aria-selected="false" tabindex="-1" data-result="${i}" id="${id}-option-${i}" class="catalog-result"><img src="${escape(track.artwork || 'assets/cover-unavailable.svg')}" alt="" width="42" height="42"><span><strong>${escape(track.title)}</strong><small>${escape(track.artist)}${track.album ? ` · ${escape(track.album)}` : ''}</small></span><small>${track.duration ? `${Math.floor(track.duration / 60)}:${String(Math.round(track.duration % 60)).padStart(2, '0')}` : ''}</small></button>`).join('');
      list.hidden = results.length === 0; input.setAttribute('aria-expanded', String(results.length > 0));
      more.hidden=nextOffset===null;
    } catch (error) {
      if (error.name === 'AbortError' || token !== generation) return;
      status.replaceChildren(document.createTextNode('Não foi possível buscar. '));
      const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'text-button'; retry.textContent = 'Tentar novamente'; retry.onclick = () => search(query,append); status.append(retry);
    } finally { if (token === generation) {input.removeAttribute('aria-busy');more.disabled=false;} }
  }
  more.addEventListener('click',()=>{if(nextOffset!==null)void search(input.value.trim(),true);});
  function updateSource(state){
    connected=state.connected;sources.hidden=!state.configured;sourceNote.hidden=!state.configured;
    if(!manualSource)source=connected?'spotify':'deezer';
    if(!connected&&source==='spotify')source='deezer';
    spotify.textContent=connected?'Spotify':'Conectar Spotify';
    sourceNote.textContent=source==='spotify'?'Escolha até 30 segundos em qualquer parte da música.':'Prévias pelo Deezer, sem conectar uma conta.';
    sources.querySelectorAll('[data-catalog-source]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.catalogSource===source)));
  }
  getSpotifyStatus().then(updateSource).catch(()=>{});
  window.addEventListener('spotifychange',event=>{updateSource(event.detail);const q=input.value.trim();if(q.length>=2)void search(q);});
  async function connectAccount(){spotify.disabled=true;try{await connectSpotify();}catch(error){onError?.(error.message);}finally{spotify.disabled=false;}}
  sources.addEventListener('click',event=>{
    const button=event.target.closest('[data-catalog-source]');if(!button)return;
    if(button.dataset.catalogSource==='spotify'&&!connected){manualSource=false;void connectAccount();return;}
    source=button.dataset.catalogSource;manualSource=true;updateSource({configured:true,connected});
    const q=input.value.trim();if(q.length>=2)void search(q);
  });
  input.addEventListener('input', () => {
    cancel(); collapse(); clear();
    const query = input.value.trim(); status.textContent = '';
    if (query.length >= 2) timer = setTimeout(() => search(query), 300);
  });
  input.addEventListener('keydown', event => {
    if (!list.hidden && ['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); highlight(highlighted + (event.key === 'ArrowDown' ? 1 : -1)); }
    if (!list.hidden && event.key === 'Enter') { event.preventDefault(); choose(highlighted >= 0 ? highlighted : 0); }
    if (!list.hidden && event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancel(); collapse(); }
  });
  list.addEventListener('click', event => { const option = event.target.closest('[data-result]'); if (option) choose(Number(option.dataset.result)); });
  selected.addEventListener('click', event => { if (event.target.closest('.clear-track')) { clear(); input.focus(); } });
  host.addEventListener('error', event => {
    if (event.target instanceof HTMLImageElement && !event.target.dataset.fallback) { event.target.dataset.fallback = 'true'; event.target.src = 'assets/cover-unavailable.svg'; }
  }, true);
  window.addEventListener('trackmetadata',event=>{
    if(current!==event.detail.index||current===null)return;
    const caption=selected.querySelector('.selection-summary span');if(caption)caption.textContent=[tracks[current].artist,trackSummary(current)].filter(Boolean).join(' · ');
  });
  return { get value() { return current; }, input, setSelection,
    requireSelection() { if (current !== null) return true; input.setCustomValidity('Escolha uma música nos resultados.'); input.reportValidity(); return false; },
    close() { cancel(); collapse(); status.textContent = ''; }, reset() { cancel(); collapse(); input.value = ''; status.textContent = ''; clear(false); } };
}

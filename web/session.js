import { tracks, musicDetails, registerTrack, resetCatalog } from './catalog-store.js';

let snapshot = null;
const values = new Map();
let queue = Promise.resolve();
let pending = 0;
export const getAccount = () => snapshot;
export const busy = () => pending > 0;
export const readAccount = (key, fallback) => values.has(key) ? values.get(key) : fallback;

export async function api(path, { method = 'GET', body, signal } = {}) {
  let response;
  try {
    response = await fetch(path, { method, credentials: 'same-origin', cache: 'no-store', signal,
      headers: { 'Content-Type': 'application/json', 'X-Ressoa-Client': 'web' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  } catch (error) { if(error.name==='AbortError')throw error;throw new Error('Sem conexão. Suas alterações ainda não foram salvas. Tente novamente.'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || 'Não foi possível concluir. Tente novamente.');
    error.status = response.status;
    if (response.status === 401 && !['/api/login', '/api/register'].includes(path)) window.dispatchEvent(new Event('sessionexpired'));
    throw error;
  }
  return data;
}

export function wireTrack(index) {
  return Number.isInteger(index) && tracks[index] ? { ...musicDetails[index], ...tracks[index], spotifyId: musicDetails[index].spotifyId || musicDetails[index].id } : null;
}
const indexTrack = value => value ? registerTrack(value) : null;
const wirePost = post => ({ ...post, track: wireTrack(post.track) });
function localPost(post, own = false) {
  return { ...post, ownerId: own ? 'me' : post.ownerId, track: indexTrack(post.track),
    feedDate:new Date(post.publishedAt||post.createdAt).toLocaleDateString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}),
    date: new Date(post.createdAt).toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) };
}
export const hydratePost = post => localPost(post,post.ownerId===snapshot.user.id);
export function hydratePublicProfile(data) {
  const hydrate=post=>localPost(post,post.ownerId===snapshot.user.id);
  return {...data,profile:{...data.profile,favorites:data.profile.favorites.map(indexTrack),background:indexTrack(data.profile.background)},
    entries:data.entries.map(hydrate),reposts:data.reposts.map(hydrate),weekly:data.weekly?hydrate(data.weekly):null};
}

export function setSnapshot(data, first = false) {
  if (first) { resetCatalog(); cancelSeen(); }
  snapshot = data;
  values.set('ressoa.entries', data.entries.map(post => localPost(post, true)));
  values.set('ressoa.public', data.publicPosts.map(post => localPost(post)));
  values.set('ressoa.profile', { ...data.profile, favorites: data.profile.favorites.map(indexTrack), background: indexTrack(data.profile.background) });
  values.set('ressoa.weekly', data.weekly ? { ...data.weekly, item: data.weekly.item ? localPost(data.weekly.item, true) : null } : null);
  values.set('ressoa.saved', data.saved);
  values.set('ressoa.social', data.social);
  values.set('ressoa.draft', { ...data.draft, track: indexTrack(data.draft.track) });
  window.dispatchEvent(new Event('accountchange'));
}

function applyAction({ action, post }) {
  const { kind, target, active } = action;
  const membership = list => active ? [...new Set([...list, target])] : list.filter(id => id !== target);
  const social = { ...snapshot.social };
  if (kind === 'like') {
    social.likes = { ...social.likes };
    if (active) social.likes[target] = ['me'];
    else delete social.likes[target];
  }
  if (kind === 'repost') social.reposts = membership(social.reposts);
  const saved = kind === 'saved' ? membership(snapshot.saved) : snapshot.saved;
  let publicPosts = snapshot.publicPosts;
  if (post.ownerId !== snapshot.user.id) {
    publicPosts = publicPosts.some(item => item.id === target)
      ? publicPosts.map(item => item.id === target ? post : item) : [...publicPosts, post];
    const local = localPost(post);
    const current = values.get('ressoa.public');
    values.set('ressoa.public', current.some(item => item.id === target)
      ? current.map(item => item.id === target ? local : item) : [...current, local]);
  }
  snapshot = { ...snapshot, social, saved, publicPosts };
  values.set('ressoa.social', social);
  values.set('ressoa.saved', saved);
  window.dispatchEvent(new Event('accountchange'));
}

export function mutate(path, method, body) {
  if (path === '/api/logout') cancelSeen();
  pending++;
  const job = queue.then(async () => {
    try {
      const payload = typeof body === 'function' ? body() : body;
      const result = await api(path, { method, body: payload });
      if (result.user) setSnapshot(result);
      else if (result.action && result.post) applyAction(result);
      return result;
    } catch (error) {
      if (error.status === 409) {
        try { setSnapshot(await api('/api/bootstrap')); } catch {}
      }
      throw error;
    } finally { pending--; }
  });
  queue = job.catch(() => {});
  return job;
}

export async function writeAccount(key, value, options={}) {
  if (key === 'ressoa.entries') return mutate('/api/entries', 'PUT', { value: value.map(wirePost), version: snapshot.versions.entries,republish:options.republish,clearDraft:options.clearDraft });
  if (key === 'ressoa.profile') return mutate('/api/profile', 'PUT', { value: { ...value, favorites: value.favorites.map(wireTrack), background: wireTrack(value.background) }, version: snapshot.versions.profile });
  if (key === 'ressoa.weekly') return value.deletedAt
    ? mutate('/api/weekly', 'DELETE', {}) : mutate('/api/weekly', 'POST', wirePost(value.item));
  if (key === 'ressoa.draft') {
    values.set(key, value);
    return mutate('/api/preference', 'PUT', { key: 'draft', value: { ...value, track: wireTrack(value.track) } });
  }
  throw new Error('Operação de armazenamento desconhecida.');
}

export async function refreshAccount() {
  await queue;
  if (pending) return false;
  const data = await api('/api/bootstrap');
  if (!pending) { setSnapshot(data); return true; }
  return false;
}

export const socialAction = (kind, target, active) => mutate('/api/action', 'POST', { kind, target, active, compact: kind !== 'follow' });

// Reading history never holds up an explicit action such as liking or posting.
let seenTimer, seenPending = null, seenWriting = false;
function cancelSeen() { clearTimeout(seenTimer); seenPending = null; }
export function saveSeen(value) {
  seenPending = { ...value };
  clearTimeout(seenTimer);
  seenTimer = setTimeout(flushSeen, 1000);
  return Promise.resolve();
}
async function flushSeen() {
  if (seenWriting || !seenPending) return;
  const value = seenPending; seenPending = null; seenWriting = true;
  try { await api('/api/preference', { method: 'PUT', body: { key: 'seen', value } }); }
  catch { /* The next reading-history update can retry without blocking the feed. */ }
  finally {
    seenWriting = false;
    if (seenPending) seenTimer = setTimeout(flushSeen, 1000);
  }
}

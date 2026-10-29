import { tracks, musicDetails, registerTrack, resetCatalog } from './catalog-store.js';

let snapshot = null;
let confirmed = null;
const values = new Map();
let queue = Promise.resolve();
let pending = 0;
let mutationRevision = 0, accountRevision = 0;
let localSeen = {};
let followStatusOffset = 0;
const actions = new Map();
const actionJobs = new Set();
export const getAccount = () => snapshot;
export const busy = () => pending > 0;
export const actionPending = (kind, target) => actions.has(`${kind}:${target}`);
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
  if (first) { resetCatalog(); cancelSeen(); actions.clear(); accountRevision++; localSeen={}; followStatusOffset=0; }
  const seen={...data.social.seen};
  for(const [id,stamp] of Object.entries(localSeen))seen[id]=Math.max(stamp,seen[id]||0);
  data={...data,social:{...data.social,seen:Object.fromEntries(Object.entries(seen).filter(([,stamp])=>Date.now()-stamp<7*86400000).sort((a,b)=>b[1]-a[1]).slice(0,300))}};
  if (!first && confirmed?.user.id === data.user.id && (confirmed.notifications?.version || 0) > (data.notifications?.version || 0)) {
    data = { ...data, notifications: confirmed.notifications };
  }
  confirmed = data;
  publishSnapshot(true);
}

export function updateNotifications(summary, userId) {
  if (!confirmed || confirmed.user.id !== userId || !summary || summary.version < (confirmed.notifications?.version || 0)) return;
  if (JSON.stringify(confirmed.notifications) === JSON.stringify(summary)) return;
  confirmed = { ...confirmed, notifications: summary };
  publishSnapshot();
}

function applyFollowResponse({ followResponse, summary }) {
  const { person, accepted } = followResponse;
  const followers = confirmed.followersPeople.filter(item => item.id !== person.id);
  if (accepted) followers.push(person);
  confirmed = { ...confirmed, followersPeople: followers,
    followRequests: confirmed.followRequests.filter(item => item.id !== person.id),
    notifications: summary.version >= (confirmed.notifications?.version || 0) ? summary : confirmed.notifications };
  publishSnapshot();
}

export async function refreshPendingFollows() {
  if (pending || !confirmed?.social.requested?.length) return false;
  const generation = accountRevision, revision = mutationRevision;
  const waiting = confirmed.social.requested;
  followStatusOffset %= waiting.length;
  const targets = [...waiting.slice(followStatusOffset), ...waiting.slice(0, followStatusOffset)].slice(0, 50);
  followStatusOffset = (followStatusOffset + targets.length) % waiting.length;
  const { people } = await api(`/api/follow-status?${new URLSearchParams({ users: targets.join(',') })}`);
  if (pending || generation !== accountRevision || revision !== mutationRevision) return false;
  const changes = people.filter(item => item.status !== 'requested');
  if (!changes.length) return false;
  const following = new Set(confirmed.social.following), requested = new Set(confirmed.social.requested);
  const followingPeople = new Map(confirmed.followingPeople.map(person => [person.id, person]));
  for (const { person, status } of changes) {
    requested.delete(person.id);
    if (status === 'following') { following.add(person.id); followingPeople.set(person.id, person); }
  }
  mutationRevision++;
  confirmed = { ...confirmed, followingPeople: [...followingPeople.values()],
    social: { ...confirmed.social, following: [...following], requested: [...requested] } };
  publishSnapshot();
  return true;
}

function publishSnapshot(full = false) {
  let data = confirmed;
  for (const operation of actions.values()) data = withAction(data, operation, operation.post);
  snapshot = data;
  if (full) {
    values.set('ressoa.entries', data.entries.map(post => localPost(post, true)));
    values.set('ressoa.profile', { ...data.profile, favorites: data.profile.favorites.map(indexTrack), background: indexTrack(data.profile.background) });
    values.set('ressoa.weekly', data.weekly ? { ...data.weekly, item: data.weekly.item ? localPost(data.weekly.item, true) : null } : null);
    values.set('ressoa.draft', { ...data.draft, track: indexTrack(data.draft.track) });
  }
  values.set('ressoa.public', data.publicPosts.map(post => localPost(post)));
  values.set('ressoa.saved', data.saved);
  values.set('ressoa.social', data.social);
  window.dispatchEvent(new Event('accountchange'));
}

function withAction(data, { kind, target, active, privateProfile }, post) {
  const membership = list => active ? [...new Set([...list, target])] : list.filter(id => id !== target);
  const social = { ...data.social };
  if (kind === 'like') {
    social.likes = { ...social.likes };
    if (active) social.likes[target] = ['me'];
    else delete social.likes[target];
  }
  if (kind === 'repost') social.reposts = membership(social.reposts);
  if (kind === 'follow') {
    // A pending follow never grants access to a private profile.
    const following = active && (!privateProfile || social.following.includes(target));
    social.following = following ? [...new Set([...social.following, target])] : social.following.filter(id => id !== target);
    social.requested = active && !following ? [...new Set([...(social.requested || []), target])] : (social.requested || []).filter(id => id !== target);
  }
  const saved = kind === 'saved' ? membership(data.saved) : data.saved;
  let publicPosts = data.publicPosts;
  if (post && post.ownerId !== data.user.id) {
    publicPosts = publicPosts.some(item => item.id === target)
      ? publicPosts.map(item => item.id === target ? post : item) : [...publicPosts, post];
  }
  return { ...data, social, saved, publicPosts };
}

function applyAction({ action, post }) {
  confirmed = withAction(confirmed, action, post);
  publishSnapshot();
}

export function mutate(path, method, body, concurrent = false) {
  if (path === '/api/logout') cancelSeen();
  pending++; mutationRevision++;
  const generation = accountRevision;
  // Social actions can run together; full account writes wait for them before
  // taking a snapshot, so an older response cannot erase a confirmed action.
  const barrier = concurrent ? queue : Promise.all([queue, ...actionJobs]);
  const job = barrier.then(async () => {
    try {
      if (generation !== accountRevision) throw new Error('A conta mudou. Reabra a tela e tente novamente.');
      const payload = typeof body === 'function' ? body() : body;
      const result = await api(path, { method, body: payload });
      if (generation === accountRevision) {
        if (result.action) applyAction(result);
        else if (result.followResponse) applyFollowResponse(result);
        else if (result.user && concurrent) {
          const post = [...result.entries, ...result.publicPosts, ...(result.weekly?.item ? [result.weekly.item] : [])].find(post => post.id === payload.target);
          applyAction({ action: payload, post });
        } else if (result.user) setSnapshot(result);
      }
      return result;
    } catch (error) {
      if (error.status === 409 && generation === accountRevision) {
        try {
          const data = await api('/api/bootstrap');
          if (generation === accountRevision) setSnapshot(data);
        } catch {}
      }
      throw error;
    } finally { pending--; }
  });
  const settled = job.catch(() => {});
  if (concurrent) {
    actionJobs.add(settled);
    settled.then(() => actionJobs.delete(settled));
  } else queue = settled;
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

export async function refreshAccount(feedOptions) {
  await Promise.all([queue, ...actionJobs]);
  if (pending) return false;
  const revision = mutationRevision, generation = accountRevision;
  const data = await (feedOptions?api('/api/feed',{method:'POST',body:feedOptions}):api('/api/bootstrap'));
  if (!pending && revision === mutationRevision && generation === accountRevision) { setSnapshot(data); return true; }
  return false;
}

export function socialAction(kind, target, active, options = {}) {
  const key = `${kind}:${target}`;
  if (actions.has(key)) return actions.get(key).promise;
  const generation = accountRevision;
  const post = options.post ? { ...wirePost(options.post), ownerId: options.post.ownerId === 'me' ? snapshot.user.id : options.post.ownerId } : null;
  const operation = { kind, target, active, post, privateProfile: options.privateProfile !== false };
  actions.set(key, operation);
  publishSnapshot();
  const job = mutate('/api/action', 'POST', { kind, target, active, compact: kind !== 'follow' }, kind !== 'follow');
  operation.promise = job.finally(() => {
    if (generation === accountRevision && actions.get(key) === operation) {
      actions.delete(key); publishSnapshot();
    }
  });
  return operation.promise;
}

// Reading history never holds up an explicit action such as liking or posting.
let seenTimer, seenPending = null, seenWriting = false;
function cancelSeen() { clearTimeout(seenTimer); seenPending = null; }
export function saveSeen(value) {
  localSeen = { ...value };
  if(confirmed)confirmed={...confirmed,social:{...confirmed.social,seen:localSeen}};
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

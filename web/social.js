const KEY = 'ressoa.social';
function clean(value = {}) {
  return {
    following: Array.isArray(value.following) ? value.following.filter(id => typeof id === 'string') : [],
    reposts: Array.isArray(value.reposts) ? value.reposts.filter(id => typeof id === 'string') : [],
    likes: value.likes && typeof value.likes === 'object' && !Array.isArray(value.likes) ? Object.fromEntries(Object.entries(value.likes).filter(([id, actors]) => typeof id === 'string' && Array.isArray(actors)).map(([id, actors]) => [id, actors.filter(actor => actor === 'me')])) : {},
    seen: value.seen && typeof value.seen === 'object' ? Object.fromEntries(Object.entries(value.seen).filter(([id, time]) => typeof id === 'string' && Number.isFinite(time))) : {}
  };
}
export function readSocial() {
  try { return clean(JSON.parse(localStorage.getItem(KEY) || '{}')); } catch { return clean(); }
}
export function writeSocial(value) { localStorage.setItem(KEY, JSON.stringify(clean(value))); }
export function authorKey(post) {
  if (post.ownerId === 'me') return 'me';
  return post.ownerId || `author:${String(post.author || post.id).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
}
export function rememberSeen(state, id, now = Date.now()) {
  const seen = { ...state.seen, [id]: now };
  state.seen = Object.fromEntries(Object.entries(seen).filter(([, time]) => now - time < 7 * 86400000).sort((a,b) => b[1] - a[1]).slice(0, 300));
}

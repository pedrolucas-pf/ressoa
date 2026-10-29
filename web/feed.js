export const FEED_LIMIT = 10;
export const FEED_REFRESH_MS = 15 * 60 * 1000;
export const FEED_LIFETIME_MS = 24 * 60 * 60 * 1000;
export function isInFeed(post,now=Date.now()) {
  if(post.visibility==='private')return false;
  if(post.kind==='weekly')return !post.feedExpiresAt||Date.parse(post.feedExpiresAt)>now;
  const published=Date.parse(post.publishedAt||post.createdAt||'');
  return Number.isFinite(published)&&published<=now+60000&&now-published<FEED_LIFETIME_MS;
}
function hash(text) { let value = 0; for (const char of text) value = (value * 31 + char.charCodeAt(0)) >>> 0; return value; }
export function wasSeen(post, seen={}, now=Date.now()) {
  const published=Date.parse(post.publishedAt||post.createdAt||'')||0;
  return Boolean(seen[post.id] && seen[post.id]>=published && now-seen[post.id]<7*86400000);
}
export function rankFeed(pool, { following = [], seen = {}, epoch = 0, now = Date.now(), limit = FEED_LIMIT } = {}) {
  const unique = [...new Map(pool.filter(post => isInFeed(post,now)).map(post => [post.id, post])).values()];
  const jitter = id => { let value = (hash(id) ^ Math.imul(epoch, 0x9e3779b9)) >>> 0; value = Math.imul(value ^ (value >>> 16), 0x85ebca6b); return (value ^ (value >>> 13)) >>> 0; };
  const published=post=>Date.parse(post.publishedAt||post.createdAt||'')||0;
  const score = post => (isSeen(post) ? 0 : 1e15) + published(post) + jitter(post.id) / 1e6;
  const order = (a,b) => score(b) - score(a);
  const result = [];
  const isSeen = post => wasSeen(post,seen,now);
  for (const group of [unique.filter(post => !isSeen(post)), unique.filter(isSeen)]) {
    const prioritized = group.filter(post => following.includes(post.ownerId)).sort(order);
    const discovery = group.filter(post => !following.includes(post.ownerId)).sort(order);
    while (result.length < limit && (prioritized.length || discovery.length)) {
      for (let i = 0; i < 2 && prioritized.length && result.length < limit; i++) result.push(prioritized.shift());
      if (discovery.length && result.length < limit) result.push(discovery.shift());
    }
  }
  return result;
}

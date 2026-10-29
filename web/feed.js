export const FEED_LIMIT = 10;
export const FEED_REFRESH_MS = 15 * 60 * 1000;
export const FEED_LIFETIME_MS = 24 * 60 * 60 * 1000;
export function isInFeed(post,now=Date.now()) {
  if(post.visibility==='private')return false;
  if(post.kind==='weekly')return !post.feedExpiresAt||Date.parse(post.feedExpiresAt)>now;
  const published=Date.parse(post.publishedAt||post.createdAt||'');
  return Number.isFinite(published)&&published<=now+60000&&now-published<FEED_LIFETIME_MS;
}
export function wasSeen(post, seen={}, now=Date.now()) {
  const published=Date.parse(post.publishedAt||post.createdAt||'')||0;
  return Boolean(seen[post.id] && seen[post.id]>=published && now-seen[post.id]<7*86400000);
}
export function rankFeed(pool, { following = [], seen = {}, now = Date.now(), limit = FEED_LIMIT } = {}) {
  const unique = [...new Map(pool.filter(post => isInFeed(post,now)).map(post => [post.id, post])).values()];
  const published=post=>Date.parse(post.publishedAt||post.createdAt||'')||0;
  const followed=new Set(following);
  return unique.sort((a,b)=>{
    const seenA=wasSeen(a,seen,now),seenB=wasSeen(b,seen,now);
    if(seenA!==seenB)return Number(seenA)-Number(seenB);
    // Recently read posts go behind the rest instead of disappearing from the feed.
    if(seenA&&seen[a.id]!==seen[b.id])return seen[a.id]-seen[b.id];
    return published(b)-published(a)||Number(followed.has(b.ownerId))-Number(followed.has(a.ownerId))||(a.id<b.id?-1:a.id>b.id?1:0);
  }).slice(0,Math.max(0,limit));
}

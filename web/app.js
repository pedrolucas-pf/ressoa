import { tracks, musicDetails } from './catalog-store.js';
import { createTrackPicker } from './track-picker.js';
import { weekKey, nextWeekLabel, lockedForWeek } from './weekly.js';
import { createPlayback } from './playback.js';
import { authorKey, rememberSeen } from './social.js';
import { rankFeed, isInFeed, FEED_LIMIT, FEED_REFRESH_MS } from './feed.js';
import { createShareImage, downloadFile } from './share.js';
import { newId } from './id.js';
import { fitText } from './text-layout.js';
import { albumArt, fitLyricArt } from './post-art.js';
import { createLyricPicker } from './lyric-picker.js';
import { ensureTrackDetails, durationLabel, trackSummary } from './track-context.js';
import { createPeopleSearch, personHref } from './people-search.js';
import { createNotifications } from './notifications.js';
import { createComments } from './comments.js';
import { createAudioExcerpt } from './audio-excerpt.js';
import { bindUsernameValidation, normalizeUsername, usernameError } from './username.js';
import { api, readAccount, writeAccount, getAccount, refreshAccount, socialAction, saveSeen, mutate, busy, actionPending, hydratePublicProfile, hydratePost } from './session.js';

const $ = selector => document.querySelector(selector);
const escape = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const svg = path => `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${path}</svg>`;
const icons = {
  more: svg('<circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none"/>'),
  bookmark: svg('<path d="M6 3h12v18l-6-4-6 4Z"/>'),
  search: svg('<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>')
};
let lyricsRequest = null;
let savingEntry=false,savingWeekly=false,savingProfile=false;
let resolveEditPublication=null;
function askEditPublication(){
  return new Promise(resolve=>{resolveEditPublication=resolve;$('#edit-publish-dialog').showModal();});
}
function finishEditPublication(value){
  const resolve=resolveEditPublication;resolveEditPublication=null;
  $('#edit-publish-dialog').close();resolve?.(value);
}
$('#edit-publish-only').addEventListener('click',()=>finishEditPublication(false));
$('#edit-publish-again').addEventListener('click',()=>finishEditPublication(true));
$('#edit-publish-dialog').addEventListener('close',()=>{const resolve=resolveEditPublication;resolveEditPublication=null;resolve?.(null);});
let editingId = null, readerId = null, shareFile = null, sharePost = null, confirmAction = null;
let social = readAccount('ressoa.social', {}), feedGeneratedAt = Date.now();
let publicPosts = readAccount('ressoa.public', []);
let visitedId=null,visitedProfile=null,profileError='',profileRequest=null,profileGeneration=0,loadingMore=false;
let linkedPost=null,linkedId=null,linkRequest=null,linkGeneration=0;

const read=(key,fallback)=>readAccount(key,fallback);
async function write(key, value, notify = true, options={}) {
  try {
    $('#account-status').textContent = 'Salvando…';
    await writeAccount(key, value, options);
    $('#account-status').textContent = `@${getAccount().user.username}`;
    return true;
  } catch (error) {
    $('#account-status').textContent = 'Não salvo · tente novamente';
    if (notify) toast(error.message);
    if (error.status === 409) { renderStories(); renderDiary(); if(page==='perfil')renderProfile(); }
    return false;
  }
}
let toastTimer;
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').hidden = true, 3500);
}

// Keep the original storage keys and entries; old mood fields are no longer used.
function validEntries(value) {
  return Array.isArray(value) ? value.filter(p => p && typeof p.id === 'string' && Number.isInteger(p.track) && tracks[p.track] && typeof p.text === 'string' && ['private', 'public'].includes(p.visibility)) : [];
}
let entries = validEntries(read('ressoa.entries', [])).map(post => ({ ...post, ownerId: 'me' }));
let saved = read('ressoa.saved', []);
saved = Array.isArray(saved) ? saved.filter(id => typeof id === 'string') : [];
let weekly = read('ressoa.weekly', null);
const defaultProfile = { displayName: 'Você', handle: getAccount().user.username, bio: '', photo: '', favorites: [], pinned: [], background: null };
function cleanProfile(value) {
  if (!value || typeof value !== 'object') return { ...defaultProfile };
  return {
    displayName: typeof value.displayName === 'string' ? value.displayName.slice(0, 50) : defaultProfile.displayName,
    handle: !usernameError(value.handle) ? normalizeUsername(value.handle) : defaultProfile.handle,
    bio: typeof value.bio === 'string' ? value.bio.slice(0, 180) : '',
    photo: typeof value.photo === 'string' && /^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/.test(value.photo) ? value.photo : '',
    isPrivate:value.isPrivate===true,
    favorites: Array.isArray(value.favorites) ? [...new Set(value.favorites.filter(index => Number.isInteger(index) && tracks[index]))].slice(0, 6) : [],
    pinned: (Array.isArray(value.pinned) ? value.pinned : typeof value.pinned === 'string' ? [value.pinned] : []).filter(id => typeof id === 'string'),
    background: Number.isInteger(value.background) && tracks[value.background] ? value.background : null
  };
}
let profileInfo = cleanProfile(read('ressoa.profile', defaultProfile));
let page = 'foryou';
let feedMode = 'foryou';
let collection = 'entries';
let storyIndex = 0;
let stories = [];
let feedPoolVersions=new Map(),feedDisplayKey='';
let feedRefreshJob=null;
const feedPosts = () => [...entries,...publicPosts,...(myWeeklyPost()?[myWeeklyPost()]:[])];
const allPosts = () => [...new Map([...(linkedPost?[linkedPost]:[]),...publicPosts,...(visitedProfile?[...visitedProfile.entries,...visitedProfile.reposts,...(visitedProfile.weekly?[visitedProfile.weekly]:[])]:[]),...entries,...(myWeeklyPost()?[myWeeklyPost()]:[])].map(post=>[post.id,post])).values()];
const cover = track => musicDetails[track]?.artwork || 'assets/cover-unavailable.svg';
const isMine = post => post.ownerId === 'me' || entries.some(entry => entry.id === post.id);
const authorName = post => isMine(post) ? profileInfo.displayName : post.author || 'Você';
const previewText = post => post.text || '...';
const authorHandle = post => {const handle=isMine(post)?profileInfo.handle:post.handle;return handle?'@'+handle:authorName(post);};
function weeklyLocked() { weekly = read('ressoa.weekly', weekly); return Boolean(weekly && weekly.weekKey === getAccount().serverWeek); }
const myWeeklyPost = () => weeklyLocked() && !weekly.deletedAt && weekly.item && tracks[weekly.item.track] ? { ...weekly.item, ownerId: 'me', kind: 'weekly' } : null;
function feedCandidates(mode=feedMode) {
  const following=new Set(social.following);
  return feedPosts().filter(post=>isInFeed(post)&&(mode==='foryou'||(!isMine(post)&&following.has(authorKey(post)))))
    .map(post=>({...post,ownerId:isMine(post)?'me':authorKey(post),featured:post.kind==='weekly'}));
}
const { stopPreview, mountPreview, mountCoverPlayer, toggleCoverPlayer } = createPlayback({ tracks, musicDetails, toast });
function spotifyBrand(track) {
  if (musicDetails[track].provider !== 'spotify') return `<a class="catalog-attribution" href="${escape(musicDetails[track].url)}" target="_blank" rel="noopener noreferrer">Ouvir no Deezer ↗</a>`;
  return `<a class="spotify-attribution" href="${escape(musicDetails[track].url)}" target="_blank" rel="noopener noreferrer" aria-label="Ouvir ${escape(tracks[track].title)} no Spotify"><img src="assets/spotify-white.svg" alt="Spotify" width="74" height="23"></a>`;
}
function trackArt(track, size = 400, excerpt = '') {
  return `<button class="cover-open" data-music="${track}" aria-label="Sobre ${escape(tracks[track].title)}${excerpt?' · Trecho: '+escape(excerpt):''}">${albumArt({artwork:cover(track),album:tracks[track].album||tracks[track].title,excerpt,size})}</button>`;
}
const coverPlay = (track,post=null) => `<button class="cover-play" data-play="${track}" ${post?`data-play-post="${escape(post.id)}"`:''} aria-label="Ouvir trecho" aria-pressed="false"><span aria-hidden="true">▶</span></button>`;
const playableArt = (track,size,excerpt,post=null) => `<div class="cover-stage">${trackArt(track,size,excerpt)}${coverPlay(track,post)}</div>`;
const publicPostLabel=()=>profileInfo.isPrivate?'Seguidores':'Pública';
document.addEventListener('error', event => {
  const image = event.target;
  if (image instanceof HTMLImageElement && image.classList.contains('album-cover') && !image.dataset.fallback) {
    image.dataset.fallback = 'true'; image.src = 'assets/cover-unavailable.svg'; image.alt = 'Capa indisponível';
  }
}, true);

$('#search-icon').innerHTML = icons.search;
$('#people-search-icon').innerHTML=icons.search;
$('#notifications-button').firstElementChild.innerHTML=svg('<circle cx="9" cy="7" r="4"/><path d="M2 21v-2a7 7 0 0 1 12-5m4-1v8m-4-4h8"/>');
const peopleSearch=createPeopleSearch($('#people-search'));
const viewport = $('#story-viewport');
viewport.tabIndex = 0;
let storySnapTarget=null,storySnapTimer,storySnapFrame;
function storyScrollTop(index) {
  const story=$('#story-track').children[index];
  if(!story)return 0;
  const top=story.getBoundingClientRect().top-viewport.getBoundingClientRect().top+viewport.scrollTop-viewport.clientTop;
  return Math.max(0,Math.min(top,viewport.scrollHeight-viewport.clientHeight));
}
function cancelStorySnap() {
  clearTimeout(storySnapTimer);cancelAnimationFrame(storySnapFrame);
  if(storySnapTarget)viewport.scrollTo({top:viewport.scrollTop,behavior:'instant'});
  storySnapTarget=null;viewport.style.removeProperty('scroll-snap-type');
}
function finishStorySnap() {
  const target=storySnapTarget;
  if(!target)return;
  clearTimeout(storySnapTimer);storySnapTarget=null;
  if(stories[target.index]?.id===target.id){
    viewport.scrollTo({top:storyScrollTop(target.index),behavior:'instant'});
  }
  storySnapFrame=requestAnimationFrame(()=>{if(!storySnapTarget)viewport.style.removeProperty('scroll-snap-type');});
}
function scrollToStory(index,smooth=false) {
  clearTimeout(storySnapTimer);cancelAnimationFrame(storySnapFrame);
  storySnapTarget={index,id:stories[index]?.id};
  // Avoid a second browser snap into the middle of an oversized weekly card.
  viewport.style.scrollSnapType='none';
  viewport.scrollTo({top:storyScrollTop(index),behavior:smooth?'smooth':'instant'});
  storySnapTimer=setTimeout(finishStorySnap,160);
}
function resizeStoryViewport() {
  viewport.setAttribute('aria-label','Role para cima ou para baixo para navegar.');
  if(!viewport.getClientRects().length)return;
  const height=Math.max(220,Math.floor(innerHeight-viewport.getBoundingClientRect().top-scrollY));
  if(viewport.style.getPropertyValue('--feed-height')!==`${height}px`){
    viewport.style.setProperty('--feed-height',`${height}px`);
    scrollToStory(storySnapTarget?.index??storyIndex);
  }
}
function positionStory(fromScroll=false) {
  $('#story-track').style.removeProperty('transform');
  resizeStoryViewport();
  if(!fromScroll)scrollToStory(storyIndex);
}

function authorMarkup(post) {
  const initials = isMine(post) ? profileInfo.displayName.slice(0, 2).toUpperCase() : post.initials || 'P';
  const photo = isMine(post) ? profileInfo.photo : post.photo;
  const id=isMine(post)?getAccount().user.id:post.ownerId;
  return `<a class="author person-link" href="${escape(personHref(id))}" data-person="${escape(id)}" aria-label="Ver perfil de ${escape(authorHandle(post))}"><span class="avatar" aria-hidden="true">${photo ? `<img src="${escape(photo)}" alt="">` : escape(initials)}</span><div>${escape(authorHandle(post))}<time>${escape(post.date || 'agora')}</time></div></a>`;
}
function saveButton(post) {
  const isSaved = saved.includes(post.id);
  return `<button class="icon-button save-button" data-save="${escape(post.id)}" ${pendingAttributes('saved',post.id)} aria-label="${isSaved ? 'Remover das' : 'Adicionar às'} guardadas: ${escape(tracks[post.track].title)}" aria-pressed="${isSaved}">${icons.bookmark}</button>`;
}

function storyMarkup(post) {
  const track = tracks[post.track];
  return `<article class="story${post.featured ? ' featured' : ''}" data-id="${escape(post.id)}" aria-label="${escape(track.title)}">
    <div class="story-art">${playableArt(post.track,undefined,post.lyricExcerpt,post)}<h2 class="track-title"><button class="track-name" data-music="${post.track}">${escape(track.title)}</button></h2><p class="artist">${escape(track.artist)}</p>${spotifyBrand(post.track)}</div>
    <div class="story-writing"><div class="story-top"><span class="story-weekly-label">Ressoa da semana</span><div class="story-label">${authorMarkup({...post,date:post.feedDate||post.date})}${followButton(post)}</div></div><div class="reflection-wrap"><div class="reflection-preview"><p class="reflection${post.text?'':' no-comment'}">${escape(previewText(post))}</p><button class="text-button read-more" data-read="${escape(post.id)}" hidden>Ler mais</button></div></div><div class="story-actions">${socialButtons(post)}${saveButton(post)}</div></div>
  </article>`;
}
function renderStories(reset = false,preserveOrder = false) {
  const previousId=stories[storyIndex]?.id,previousIndex=storyIndex;
  const following = new Set(social.following);
  const pool = feedCandidates();
  const candidates=new Map(pool.map(post=>[post.id,post]));
  const versions=new Map([...candidates].map(([id,post])=>[id,post.publishedAt||post.createdAt||'']));
  const hasNew=[...versions].some(([id,version])=>feedPoolVersions.get(id)!==version);feedPoolVersions=versions;
  const ranking={following:social.following,seen:social.seen};
  let next;
  if(preserveOrder&&!hasNew){
    next=stories.filter(post=>candidates.has(post.id)).map(post=>candidates.get(post.id));
    const retained=new Set(next.map(post=>post.id));
    next.push(...rankFeed([...candidates.values()].filter(post=>!retained.has(post.id)),{...ranking,limit:FEED_LIMIT-next.length}));
  }else{
    next=rankFeed(pool,ranking);
  }
  const displayKey=JSON.stringify([feedMode,next.map(post=>[post,tracks[post.track],cover(post.track)]),social.likes,social.reposts,social.following,social.requested,saved,profileInfo.displayName,profileInfo.photo]);
  if(preserveOrder&&!hasNew&&displayKey===feedDisplayKey){stories=next;return false;}
  feedDisplayKey=displayKey;stories=next;
  document.querySelectorAll('[data-feed-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.feedMode===feedMode)));
  $('#feed-empty-title').textContent=feedMode==='following'?(following.size?'Nenhum Ressoa novo de quem você segue.':'Você ainda não segue ninguém.'):'Nenhum Ressoa novo.';
  $('#feed-empty-write').hidden=feedMode==='following';
  $('#feed-find-people').hidden=feedMode!=='following';
  const shouldReset=reset&&(!preserveOrder||hasNew),activeId=shouldReset?null:previousId;
  const retained = stories.findIndex(post => post.id === activeId); storyIndex = retained >= 0 ? retained : shouldReset?0:Math.min(previousIndex,Math.max(0,stories.length-1));
  $('#story-track').innerHTML = stories.map(storyMarkup).join('');
  $('#feed-empty').hidden = stories.length > 0;
  $('#story-viewport').hidden = stories.length === 0;
  document.querySelectorAll('.story.featured').forEach(story => { const post = stories.find(item => item.id === story.dataset.id); story.style.setProperty('--weekly-art', `url(${JSON.stringify(cover(post.track))})`); });
  const navigation=$('#story-progress');navigation.hidden=stories.length<2;navigation.style.setProperty('--feed-count',stories.length);
  navigation.innerHTML = stories.map((post,index)=>`<button type="button" class="feed-step${post.featured?' featured-step':''}" data-index="${index}" aria-label="${post.featured?'Ressoa da semana':'Ressoa'} ${index+1} de ${stories.length}: ${escape(tracks[post.track].title)}"></button>`).join('');
  moveStory(storyIndex, false);
  scheduleTextLayout();
  return hasNew;
}

let layoutFrame;
function scheduleTextLayout() {
  cancelAnimationFrame(layoutFrame);
  layoutFrame=requestAnimationFrame(()=>{
    resizeStoryViewport();
    fitLyricArt();
    document.querySelectorAll('.story').forEach(story=>{
      const post=stories.find(post=>post.id===story.dataset.id);if(!post)return;
      const wrap=story.querySelector('.reflection-wrap'),preview=story.querySelector('.reflection-preview'),text=story.querySelector('.reflection'),more=story.querySelector('.read-more');
      const cover=story.querySelector('.cover-stage').getBoundingClientRect();
      const actions=story.querySelector('.story-actions');
      wrap.style.height=`${Math.max(0,cover.bottom-wrap.getBoundingClientRect().top)}px`;
      const title=story.querySelector('.track-title'),titleBox=title.getBoundingClientRect();
      const titleLine=parseFloat(getComputedStyle(title).lineHeight)||titleBox.height;
      actions.style.marginTop=`${Math.max(0,titleBox.top-cover.bottom+(titleLine-actions.getBoundingClientRect().height)/2)}px`;
      if(!wrap.clientHeight)return;
      preview.style.removeProperty('--reflection-offset');
      text.style.maxHeight='none';text.textContent=previewText(post);text.classList.toggle('no-comment',!post.text);more.hidden=true;
      const fullHeight=text.scrollHeight,lineHeight=parseFloat(getComputedStyle(text).lineHeight);
      const style=getComputedStyle(wrap),available=Math.max(0,wrap.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom));
      const isLong=fullHeight>lineHeight*5||fullHeight>available+1;
      story.classList.toggle('long-reflection',isLong);
      if(fullHeight>available+1) {
        more.hidden=false;
        const gap=parseFloat(getComputedStyle(more).marginTop);
        const lines=Math.max(0,Math.floor((available-more.offsetHeight-gap)/lineHeight));
        text.style.maxHeight=`${lines*lineHeight}px`;
        fitText(text,previewText(post));
      }
      if(!isLong) {
        // Follow the cover's center, keeping clear of the author and actions on small screens.
        const contentTop=wrap.getBoundingClientRect().top+parseFloat(style.paddingTop),height=preview.getBoundingClientRect().height;
        const offset=Math.max(0,Math.min(available-height,cover.top+cover.height/2-contentTop-height/2));
        preview.style.setProperty('--reflection-offset',`${offset}px`);
      }
    });
    const byId=new Map(allPosts().map(post=>[post.id,post]));
    document.querySelectorAll('#profile-content .diary-card,#diary-entries .diary-card').forEach(card=>{const post=byId.get(card.dataset.id);if(post){const text=card.querySelector('.reflection'),placeholder=!post.text&&Boolean(card.closest('#profile-content'));text.classList.toggle('no-comment',placeholder);fitText(text,placeholder?'...':post.text);}});
    const featured=visitedId?visitedProfile?.weekly:myWeeklyPost(),weeklyText=$('#profile-content .weekly-reflection');
    if(featured&&weeklyText)fitText(weeklyText,previewText(featured));
  });
}
const textObserver=new ResizeObserver(scheduleTextLayout);
textObserver.observe($('#story-viewport'));textObserver.observe($('#profile-content'));
textObserver.observe($('#diary-entries'));
document.fonts.ready.then(scheduleTextLayout);
function moveStory(index, markSeen = true, fromScroll = false) {
  if(markSeen&&feedRefreshJob)return;
  if(markSeen&&stories.length&&index>=stories.length){
    void refreshFeedBatch(true);return;
  }
  if (markSeen && Date.now() - feedGeneratedAt >= FEED_REFRESH_MS) {
    feedGeneratedAt = Date.now();void refreshView();
  }
  const next = Math.max(0,Math.min(index,stories.length-1));
  if(fromScroll&&next===storyIndex)return;
  if(markSeen && next!==storyIndex && stories[storyIndex]) { rememberSeen(social,stories[storyIndex].id); saveSeen(social.seen).catch(() => {}); }
  stopPreview(); storyIndex=next;
  $('#for-you').classList.toggle('weekly-view',Boolean(stories[storyIndex]?.featured));
  const focusInside=$('#story-track').contains(document.activeElement);
  positionStory(fromScroll);
  document.querySelectorAll('.story').forEach((story,i)=>{story.inert=i!==storyIndex;story.setAttribute('aria-hidden',String(i!==storyIndex));});
  document.querySelectorAll('.feed-step').forEach((step,i)=>{step.classList.toggle('passed',i<storyIndex);if(i===storyIndex)step.setAttribute('aria-current','true');else step.removeAttribute('aria-current');});
  $('#story-position').textContent=stories.length?`${tracks[stories[storyIndex].track].title} · ${authorHandle(stories[storyIndex])}`:'Sem publicações.';
  if(focusInside)$('#story-viewport').focus({preventScroll:true}); mountStoryPreview();
}
$('#story-progress').addEventListener('click',event=>{const step=event.target.closest('[data-index]');if(step)moveStory(Number(step.dataset.index));});
function selectFeed(mode) {
 if(!['foryou','following'].includes(mode)||mode===feedMode)return;
 clearSwipeCorrection();clearPullIndicator();
 if(stories[storyIndex]){rememberSeen(social,stories[storyIndex].id);void saveSeen(social.seen);}
 feedMode=mode;feedPoolVersions.clear();feedDisplayKey='';
 renderStories(true);
}
$('#feed-filters').addEventListener('click',event=>{const button=event.target.closest('[data-feed-mode]');if(button)selectFeed(button.dataset.feedMode);});
$('#feed-filters').addEventListener('keydown',event=>{
 if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
 const buttons=[...document.querySelectorAll('[data-feed-mode]')],current=buttons.indexOf(event.target);
 if(current<0)return;
 event.preventDefault();event.stopPropagation();
 const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(current+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
 selectFeed(buttons[next].dataset.feedMode);buttons[next].focus();
});
$('#feed-find-people').addEventListener('click',()=>{if($('#people-search').dataset.open!=='true')$('#toggle-people-search').click();$('#people-query').focus();});
function refreshFeedBatch(wrap=false) {
 if(feedRefreshJob)return feedRefreshJob;
 clearSwipeCorrection();clearPullIndicator();
 if(stories[storyIndex]){rememberSeen(social,stories[storyIndex].id);void saveSeen(social.seen);}
 const mode=feedMode,current=new Map(stories.map(post=>[post.id,post.publishedAt||post.createdAt]));
 const button=$('#refresh-feed');button.disabled=true;button.setAttribute('aria-busy','true');$('#story-viewport').setAttribute('aria-busy','true');
 feedRefreshJob=(async()=>{
  try{
   const refreshed=await refreshAccount({mode,seen:{...social.seen}});
   if(!refreshed){if(wrap&&mode===feedMode)moveStory(0,false);return;}
   feedGeneratedAt=Date.now();
   if(mode!==feedMode){renderStories(false,true);return;}
   const next=rankFeed(feedCandidates(mode),{following:social.following,seen:social.seen});
   const changed=next.some(post=>current.get(post.id)!==(post.publishedAt||post.createdAt));
   if(changed)renderStories(true);
   else{renderStories(false,true);if(wrap)moveStory(0,false);if(!wrap)toast('Nenhum Ressoa novo.');}
  }catch(error){if(wrap&&mode===feedMode)moveStory(0,false);toast(error.message);}
  finally{button.disabled=false;button.removeAttribute('aria-busy');$('#story-viewport').removeAttribute('aria-busy');feedRefreshJob=null;}
 })();
 return feedRefreshJob;
}
$('#refresh-feed').addEventListener('click',()=>void refreshFeedBatch());

const savingPosts=new Set();
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-save]');
  if(!button||savingPosts.has(button.dataset.save))return;
  const id=button.dataset.save;savingPosts.add(id);button.disabled=true;
  try{await toggleSave(id);}finally{savingPosts.delete(id);button.disabled=false;}
});
async function toggleSave(id) {
  const post=allPosts().find(post => post.id === id);
  if (!post || actionPending('saved',id)) return;
  const existed = saved.includes(id);
  let stored = false;
  try { await socialAction('saved', id, !existed, {post}); stored = true; } catch(error) { toast(error.message); return; }
  document.querySelectorAll('[data-save]').forEach(button => {
    if (button.dataset.save !== id) return;
    const title = tracks[allPosts().find(post => post.id === id).track].title;
    button.setAttribute('aria-pressed', String(!existed));
    button.setAttribute('aria-label', `${existed ? 'Adicionar às' : 'Remover das'} guardadas: ${title}`);
  });
  if (page === 'diario' && collection === 'saved') {
    renderDiary();
    $('[data-collection="saved"]').focus({ preventScroll: true });
  }
  if (stored) toast(existed ? 'Removida das guardadas.' : 'Ressoa guardada.');
}

// Native vertical scrolling is shared by all devices.
let lastGesture = 0;
let scrollFrame, swipeCorrection=null,swipeCorrectionTimer,mobileTouch=null,lastWheelAt=0,wheelStartedAtEnd=false,wheelStartedAtStart=false;
const atFeedEnd=()=>stories.length>0&&storyIndex===stories.length-1&&viewport.scrollTop>=storyScrollTop(stories.length-1)-3;
const atFeedStart=()=>stories.length>0&&storyIndex===0&&viewport.scrollTop<=3;
function clearPullIndicator() {
  const button=$('#refresh-feed');button.removeAttribute('data-pulling');button.removeAttribute('data-pull-ready');button.style.removeProperty('--pull-turn');
}
function clearSwipeCorrection(){clearTimeout(swipeCorrectionTimer);swipeCorrection=null;}
function finishSwipeCorrection(){
  const swipe=swipeCorrection;swipeCorrection=null;
  if(!swipe||page!=='foryou'||feedRefreshJob||stories[swipe.index]?.id!==swipe.id||document.querySelector('dialog[open]'))return;
  // Let native momentum finish; only help when a weekly card traps the gesture.
  if(storyIndex===swipe.from||(storyIndex===swipe.index&&Math.abs(viewport.scrollTop-storyScrollTop(swipe.index))>3)){
    scrollToStory(swipe.index,!matchMedia('(prefers-reduced-motion: reduce)').matches);
  }
}
viewport.addEventListener('scroll',()=>{
  if(page!=='foryou'||document.querySelector('dialog[open]'))return;
  if(storySnapTarget){clearTimeout(storySnapTimer);storySnapTimer=setTimeout(finishStorySnap,160);}
  if(swipeCorrection){clearTimeout(swipeCorrectionTimer);swipeCorrectionTimer=setTimeout(finishSwipeCorrection,110);}
  cancelAnimationFrame(scrollFrame);
  scrollFrame=requestAnimationFrame(()=>{
    if(!viewport.clientHeight||feedRefreshJob)return;
    let index=storyIndex,distance=Infinity;
    for(let i=0;i<stories.length;i++){
      const delta=Math.abs(viewport.scrollTop-storyScrollTop(i));
      if(delta<distance){distance=delta;index=i;}
    }
    if(index!==storyIndex){lastGesture=Date.now();moveStory(index,true,true);}
  });
},{passive:true});
viewport.addEventListener('touchstart',event=>{
  clearSwipeCorrection();clearPullIndicator();cancelStorySnap();
  mobileTouch=event.touches.length===1?{x:event.touches[0].clientX,y:event.touches[0].clientY,index:storyIndex,atStart:atFeedStart(),atEnd:atFeedEnd()}:null;
},{passive:true});
viewport.addEventListener('touchmove',event=>{
  if(!mobileTouch?.atStart||event.touches.length!==1||feedRefreshJob)return;
  const dx=event.touches[0].clientX-mobileTouch.x,dy=event.touches[0].clientY-mobileTouch.y;
  if(dy<=0||Math.abs(dy)<=Math.abs(dx)*1.5){clearPullIndicator();return;}
  const button=$('#refresh-feed');button.dataset.pulling='true';button.dataset.pullReady=String(dy>=75);button.style.setProperty('--pull-turn',`${Math.min(1,dy/75)*300}deg`);
},{passive:true});
viewport.addEventListener('touchend',event=>{
  const start=mobileTouch;mobileTouch=null;clearPullIndicator();
  if(!start||event.touches.length||!event.changedTouches.length)return;
  const dx=event.changedTouches[0].clientX-start.x,dy=event.changedTouches[0].clientY-start.y;
  if(Math.abs(dy)>15)lastGesture=Date.now();
  if(Math.abs(dy)<=55||Math.abs(dy)<=Math.abs(dx)*1.5||window.getSelection()?.toString())return;
  if(start.atStart&&atFeedStart()&&dy>=75){void refreshFeedBatch();return;}
  const target=start.index+(dy<0?1:-1);
  if(target>=stories.length){if(start.atEnd&&atFeedEnd())void refreshFeedBatch(true);return;}
  const index=Math.max(0,target),id=stories[index]?.id;
  if(index!==start.index&&(stories[start.index]?.featured||stories[index]?.featured)){
    swipeCorrection={from:start.index,index,id};swipeCorrectionTimer=setTimeout(finishSwipeCorrection,110);
  }
},{passive:true});
viewport.addEventListener('touchcancel',()=>{mobileTouch=null;clearPullIndicator();},{passive:true});
window.addEventListener('resize',scheduleTextLayout);
textObserver.observe($('.header'));
viewport.addEventListener('click', event => {
 const more=event.target.closest('.read-more');if(more)openPost(more.dataset.read);
});
viewport.addEventListener('wheel', event => {
 const now=Date.now();
 if(now-lastWheelAt>250){wheelStartedAtEnd=atFeedEnd();wheelStartedAtStart=atFeedStart();}
 lastWheelAt=now;
 if(wheelStartedAtEnd&&atFeedEnd()&&event.deltaY>40&&Math.abs(event.deltaY)>Math.abs(event.deltaX)&&now-lastGesture>450){
  event.preventDefault();wheelStartedAtEnd=false;lastGesture=now;void refreshFeedBatch(true);
 }else if(wheelStartedAtStart&&atFeedStart()&&event.deltaY<-40&&Math.abs(event.deltaY)>Math.abs(event.deltaX)&&now-lastGesture>450){
  event.preventDefault();wheelStartedAtStart=false;lastGesture=now;void refreshFeedBatch();
 }
}, { passive: false });

document.addEventListener('keydown', event => {
  if (page !== 'foryou' || document.querySelector('dialog[open]') || event.target.closest('input, select, textarea, [contenteditable="true"]') || event.altKey || event.ctrlKey || event.metaKey) return;
  const vertical=['ArrowDown','ArrowUp','PageDown','PageUp'].includes(event.key);
  if (event.key === 'ArrowRight' || event.key === 'ArrowLeft' || vertical) {
    event.preventDefault();
    moveStory(storyIndex + (['ArrowRight','ArrowDown','PageDown'].includes(event.key) ? 1 : -1));
  }
});


function diaryMarkup(post, {reposted=false,pinned=false,inProfile=false}={}) {
  const track=tracks[post.track];
  const authorId=isMine(post)?getAccount().user.id:post.ownerId,photo=isMine(post)?profileInfo.photo:post.photo;
  const badge=reposted?`<a class="repost-badge person-link" href="${escape(personHref(authorId))}" data-person="${escape(authorId)}" aria-label="Repost de ${escape(authorHandle(post))}" title="Repost de ${escape(authorHandle(post))}"><span aria-hidden="true">↻</span><span class="avatar" aria-hidden="true">${photo?`<img src="${escape(photo)}" alt="">`:escape(post.initials||authorName(post).slice(0,2).toUpperCase())}</span><span class="repost-name">${escape(authorHandle(post))}</span></a>`:'';
  return `<article class="diary-post diary-card${reposted?' repost-card':''}" data-id="${escape(post.id)}">${pinned?'<span class="pin-label">Fixada</span>':''}${badge}<button class="diary-card-open" data-read="${escape(post.id)}" aria-label="Abrir ressoa: ${escape(track.title)}">${albumArt({artwork:cover(post.track),album:track.album||track.title,excerpt:post.lyricExcerpt,size:250,lazy:true})}<div class="diary-card-copy"><h2 class="track-title">${escape(track.title)}</h2><p class="artist">${escape(track.artist)}</p><p class="reflection${inProfile&&!post.text?' no-comment':''}">${escape(inProfile?previewText(post):post.text)}</p><p class="privacy">${isMine(post)?post.visibility==='private'?'Só você':publicPostLabel():escape(authorHandle(post))} · ${escape(post.date||'agora')}</p></div></button>${coverPlay(post.track,post)}</article>`;
}
function renderDiary() {
 const featured=myWeeklyPost();
 $('#weekly-selection').innerHTML=featured?`<div class="weekly-preview">${playableArt(featured.track,48,featured.lyricExcerpt,featured)}<div><p>${escape(tracks[featured.track].title)}</p>${spotifyBrand(featured.track)}</div></div>`:'<span class="muted">'+(weeklyLocked()?'Destaque apagado':'Não definida')+'</span>';
 $('#define-weekly').textContent=weeklyLocked()?'Escolha usada':'Definir';$('#define-weekly').disabled=weeklyLocked();$('#delete-weekly').hidden=!featured;
 $('#weekly-lock-note').textContent=weeklyLocked()?`Nova escolha em ${nextWeekLabel()}, à 0h de Brasília.`:'Uma escolha por semana · independente do diário.';
 document.querySelectorAll('[data-collection]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.collection===collection)));
 const query=$('#search').value.trim().toLocaleLowerCase('pt-BR');
 const source=collection==='saved'?allPosts().filter(post=>saved.includes(post.id)):entries;
 const filtered=source.filter(post=>[tracks[post.track].title,tracks[post.track].artist,post.text,post.author].join(' ').toLocaleLowerCase('pt-BR').includes(query));
 $('#diary-entries').innerHTML=filtered.length?filtered.map(post=>diaryMarkup(post)).join(''):`<p class="empty">${query?'Nenhum resultado.':collection==='saved'?'Nenhuma ressoa guardada.':'Nenhuma ressoa ainda.'}</p>`;
 scheduleTextLayout();
}

document.querySelectorAll('[data-collection]').forEach(button => button.addEventListener('click', () => {
  collection = button.dataset.collection;
  $('#search').value = '';
  renderDiary();
}));
$('#search').addEventListener('input', renderDiary);
$('#diary-entries').addEventListener('click', event => {
  const readButton = event.target.closest('[data-read]');
  const feature = event.target.closest('[data-weekly]');
  if (readButton) openPost(readButton.dataset.read);
  if (feature) setWeekly(feature.dataset.weekly);
});
function route() {
  stopPreview();
  peopleSearch.close();
  let postTarget=null;
  if(location.hash.startsWith('#ressoa/')){try{postTarget=decodeURIComponent(location.hash.slice(8));}catch{postTarget='invalid';}}
  if(!postTarget&&linkedId!==null){linkRequest?.abort();linkGeneration++;linkedId=null;linkedPost=null;if($('#reader').open)$('#reader').close();}
  const prefix='#pessoa/';
  let target=null;
  if(location.hash.startsWith(prefix)){try{target=decodeURIComponent(location.hash.slice(prefix.length));}catch{target='invalid';}}
  if(target===getAccount().user.id)target=null;
  if(target!==visitedId){profileRequest?.abort();profileGeneration++;visitedId=target;visitedProfile=null;profileError='';}
  // Existing #descobrir and #guardadas links remain usable.
  page = location.hash === '#perfil'||location.hash.startsWith(prefix) ? 'perfil' : ['diario', 'guardadas'].includes(location.hash.slice(1)) ? 'diario' : 'foryou';
  if (location.hash === '#guardadas') collection = 'saved';
  $('#for-you').hidden = page !== 'foryou';
  $('#diary').hidden = page !== 'diario';
  $('#profile').hidden = page !== 'perfil';
  document.querySelectorAll('[data-page]').forEach(link => {
    if (link.dataset.page === page) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  if (page === 'diario') renderDiary();
  if (page === 'perfil') {renderProfile();if(visitedId&&!visitedProfile&&!profileError)loadVisitedProfile();}
  applyProfileBackground();
  if (page === 'foryou') {renderStories(false,true);mountStoryPreview();}
  if(postTarget&&!$('#app-shell').hidden)openLinkedPost(postTarget);
  scheduleTextLayout();
}
window.addEventListener('hashchange', () => { route(); window.scrollTo(0, 0); });


async function openLinkedPost(id) {
 if(linkedId===id)return;
 linkRequest?.abort();const token=++linkGeneration;linkedId=id;linkedPost=null;
 const request=new AbortController();linkRequest=request;
 stopPreview();
 $('#reader-content').innerHTML='<h2 id="reader-title">Carregando ressoa…</h2><p class="form-note" role="status">Só um instante.</p>';
 if(!$('#reader').open)$('#reader').showModal();
 try {
  const data=await api(`/api/post?${new URLSearchParams({id})}`,{signal:request.signal});
  if(token!==linkGeneration)return;
  linkedPost=hydratePost(data.post);openPost(id,linkedPost);
 }catch(error){
  if(error.name==='AbortError'||token!==linkGeneration)return;
  $('#reader-content').innerHTML=`<h2 id="reader-title">Ressoa indisponível</h2><p class="form-note" role="status">${escape(error.status===404?'Essa ressoa foi apagada, ficou privada ou o destaque terminou.':error.message)}</p>`;
 }finally{if(token===linkGeneration)linkRequest=null;}
}
function openPost(id,post=allPosts().find(value=>value.id===id)) {
 if(!post)return;stopPreview();readerId=id;
 const track=tracks[post.track],own=isMine(post),pub=post.visibility!=='private';
 $('#reader-content').innerHTML=`<div class="reader-cover">${playableArt(post.track,140,post.lyricExcerpt,post)}</div><h2 id="reader-title">${escape(track.title)}</h2><p class="artist">${escape(track.artist)}</p>${spotifyBrand(post.track)}<div class="reader-author">${authorMarkup(post)}</div><p class="reader-text" ${post.text?'':'hidden'}>${escape(post.text)}</p><div class="reader-social">${pub?socialButtons(post):''}${saveButton(post)}</div><div class="post-commands">${own&&post.kind!=='weekly'?`<button class="text-button" data-edit="${escape(id)}">Editar</button><button class="text-button" data-delete="${escape(id)}">Apagar</button>`:''}${own&&post.kind==='weekly'?'<button class="text-button" data-delete-weekly>Apagar destaque</button>':''}${own&&pub?`<button class="text-button" data-interactions="${escape(id)}">Curtidas e reposts</button>`:''}${own&&pub&&post.kind!=='weekly'?`<button class="text-button" data-feature="${escape(id)}" ${weeklyLocked()?'disabled':''}>Usar música na semana</button><button class="text-button" data-reader-pin="${escape(id)}">${profileInfo.pinned.includes(id)?'Desafixar':'Fixar no perfil'}</button>`:''}</div>`;
 if(!$('#reader').open)$('#reader').showModal();
}
$('#reader').addEventListener('close',()=>{
 stopPreview();
 if(location.hash.startsWith('#ressoa/')){linkRequest?.abort();linkGeneration++;linkedId=null;linkedPost=null;history.replaceState(null,'','#foryou');}
 mountStoryPreview();
});

document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => document.getElementById(button.dataset.close).close()));
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => {
  if (event.target !== dialog) return;
  const rect = dialog.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
}));


function setWeekly(id) {
 if(weeklyLocked()){toast(`Sua próxima escolha será em ${nextWeekLabel()}.`);return false;}
 const source=entries.find(post=>post.id===id);if(!source)return false;
 $('#reader').close();$('#define-weekly').click();weeklyPicker.setSelection(source.track,false);weeklyAudio.set(source.track);renderExcerptChoice('weekly');$('#weekly-form').elements.reflection.value='';$('#weekly-form').elements.reflection.focus();return true;
}

$('#define-weekly').addEventListener('click', () => {
  if (weeklyLocked()) return;
  weeklyPicker.reset(); $('#weekly-form').reset();weeklyAudio.set(null);renderExcerptChoice('weekly');
  $('#weekly-dialog').showModal();
});
$('#weekly-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (savingWeekly) return;
  if (weeklyLocked()) { toast(`Sua próxima escolha será em ${nextWeekLabel()}.`); return; }
  if (!weeklyPicker.requireSelection()) return;
  const text = event.currentTarget.elements.reflection.value.trim();
  const entry = makeEntry(weeklyPicker.value, text, 'public',event.currentTarget.elements.lyricExcerpt.value,weeklyAudio.value);
  savingWeekly=true;
  const stored=await saveNewEntry(entry,true);savingWeekly=false;
  if(!stored)return;
  $('#weekly-dialog').close(); renderStories(); renderDiary(); renderProfile(); toast('Ressoa da semana definida.');
});

const form = $('#entry-form');
const pickerOptions = { onPreview: mountPreview, onStop: stopPreview, onError: toast };
const composerPicker = createTrackPicker($('#composer-track-picker'), { ...pickerOptions, onChange:index=>trackChanged('entry',index) });
const weeklyPicker = createTrackPicker($('#weekly-track-picker'), {...pickerOptions,onChange:index=>trackChanged('weekly',index)});
const entryAudio=createAudioExcerpt({host:$('#entry-audio-choice'),musicDetails,stopPreview,onChange:persistDraft});
const weeklyAudio=createAudioExcerpt({host:$('#weekly-audio-choice'),musicDetails,stopPreview});
const lyricPicker=createLyricPicker({dialog:$('#lyric-picker'),api,tracks,musicDetails,async onSelect(scope,value,{track,audioStart}){
 const target=scope==='weekly'?$('#weekly-form'):form,picker=scope==='weekly'?weeklyPicker:composerPicker,audio=scope==='weekly'?weeklyAudio:entryAudio;
 if(picker.value!==track)throw new Error('A música mudou. Abra a letra novamente.');
 if(audioStart!==null&&!await audio.alignTo(audioStart))throw new Error('Não foi possível ajustar o áudio. Tente novamente ou desative a sincronização.');
 if(picker.value!==track)throw new Error('A música mudou. Abra a letra novamente.');
 target.elements.lyricExcerpt.value=value;renderExcerptChoice(scope);if(scope==='entry')persistDraft();
}});
function trackChanged(scope,index) {
 (scope==='weekly'?weeklyAudio:entryAudio).set(index);
 const target=scope==='weekly'?$('#weekly-form'):form;target.elements.lyricExcerpt.value='';renderExcerptChoice(scope,index);if(scope==='entry')persistDraft();
}
function renderExcerptChoice(scope,index) {
 const target=scope==='weekly'?$('#weekly-form'):form,picker=scope==='weekly'?weeklyPicker:composerPicker;
 if(index===undefined)index=picker.value;
 const value=index===null?'':target.elements.lyricExcerpt.value;
 $(`#${scope}-excerpt-choice`).innerHTML=`<button type="button" class="text-button" data-choose-excerpt="${scope}" ${index===null?'disabled':''}>${value?'Trocar trecho':'Escolher trecho da letra'}</button>${value?`<button type="button" class="text-button" data-remove-excerpt="${scope}">Usar só a capa</button><div class="excerpt-selected">${albumArt({artwork:cover(index),album:tracks[index].album||tracks[index].title,excerpt:value,size:140})}</div>`:''}`;
 requestAnimationFrame(()=>fitLyricArt($(`#${scope}-excerpt-choice`)));
}
document.addEventListener('click',event=>{
 const choose=event.target.closest('[data-choose-excerpt]'),remove=event.target.closest('[data-remove-excerpt]');if(!choose&&!remove)return;
 const scope=(choose||remove).dataset[choose?'chooseExcerpt':'removeExcerpt'],target=scope==='weekly'?$('#weekly-form'):form,picker=scope==='weekly'?weeklyPicker:composerPicker;
 if(remove){target.elements.lyricExcerpt.value='';renderExcerptChoice(scope);if(scope==='entry')persistDraft();return;}
 if(picker.requireSelection())lyricPicker.open({scope,track:picker.value,excerpt:target.elements.lyricExcerpt.value,audio:(scope==='weekly'?weeklyAudio:entryAudio).value});
});

function openComposer(id = null) {
 stopPreview(); const existing=id?entries.find(post=>post.id===id):null;if(id&&!existing)return;
 editingId=existing?.id||null;const draft=existing?{text:existing.text,track:existing.track,visibility:existing.visibility,lyricExcerpt:existing.lyricExcerpt,audioExcerpt:existing.audioExcerpt}:read('ressoa.draft',{});
 form.reset();composerPicker.reset();form.elements.reflection.setCustomValidity('');
 if(typeof draft?.text==='string')form.elements.reflection.value=draft.text;
 if(Number.isInteger(draft?.track)&&tracks[draft.track])composerPicker.setSelection(draft.track,false);
 if(draft?.visibility==='public')form.elements.visibility.value='public';
 form.elements.lyricExcerpt.value=draft?.lyricExcerpt||'';renderExcerptChoice('entry');
 entryAudio.set(composerPicker.value,draft?.audioExcerpt||null);
 $('#composer-title').textContent=editingId?'Editar ressoa':'Escrever uma ressoa';$('#entry-form [type="submit"]').textContent=editingId?'Salvar alterações':'Salvar ressoa';$('#composer').showModal();
}

let draftTimer;
function persistDraft() {
  if (editingId) return;
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    write('ressoa.draft', { text: form.elements.reflection.value, track: composerPicker.value, visibility: form.elements.visibility.value,lyricExcerpt:form.elements.lyricExcerpt.value,audioExcerpt:entryAudio.value });
  }, 800);
}
$('#write-entry').addEventListener('click', () => openComposer());
form.addEventListener('input', persistDraft);
form.addEventListener('change', persistDraft);
form.elements.reflection.addEventListener('input', event => event.target.setCustomValidity(''));
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (savingEntry) return;
  clearTimeout(draftTimer);
  const text = form.elements.reflection.value.trim();
  if (!composerPicker.requireSelection()) return;
  savingEntry=true;
  const submit=$('#entry-form [type="submit"]'),submitLabel=submit.textContent;
  submit.disabled=true;submit.textContent='Salvando…';
  $('#entry-form [type="submit"]').setAttribute('aria-busy','true');
  try {
  let entry;
  if (editingId) {
    const existing = entries.find(post => post.id === editingId);
    if (!existing) { toast('Esta ressoa não está mais disponível.'); return; }
    entry = { ...existing, track: composerPicker.value, text, visibility: form.elements.visibility.value,lyricExcerpt:form.elements.lyricExcerpt.value,audioExcerpt:entryAudio.value,updatedAt: new Date().toISOString() };
    const updated = entries.map(post => post.id === editingId ? entry : post);
    const changed=existing.track!==entry.track||existing.text!==entry.text||existing.visibility!==entry.visibility||(existing.lyricExcerpt||'')!==entry.lyricExcerpt||JSON.stringify(existing.audioExcerpt||null)!==JSON.stringify(entry.audioExcerpt);
    let publishAgain=false;
    if(changed&&existing.visibility==='public'&&entry.visibility==='public'){
      publishAgain=await askEditPublication();if(publishAgain===null)return;
    }
    if (!await write('ressoa.entries', updated,true,{republish:publishAgain?entry.id:undefined})) return;
  } else {
    entry = makeEntry(composerPicker.value, text, form.elements.visibility.value,form.elements.lyricExcerpt.value,entryAudio.value);
    if (!await saveNewEntry(entry)) return;
  }
  const wasEditing = Boolean(editingId); editingId = null;
  form.reset(); $('#composer').close();
  collection = 'entries'; $('#search').value = '';
  renderStories(); renderDiary(); renderProfile();
  if (wasEditing) openPost(entry.id);
  toast(wasEditing ? 'Alterações salvas.' : 'Ressoa salva.');
  } finally { savingEntry=false;submit.disabled=false;submit.textContent=submitLabel;submit.removeAttribute('aria-busy'); }
});


function makeEntry(track,text,visibility,lyricExcerpt='',audioExcerpt=null) {return{id:newId(),track,text,visibility,lyricExcerpt,audioExcerpt,ownerId:'me',author:'Você',initials:'P',createdAt:new Date().toISOString(),date:new Date().toLocaleDateString('pt-BR',{timeZone:'America/Sao_Paulo'})};}
async function saveNewEntry(entry,feature=false) {
 if(feature){
  if(weeklyLocked()){toast(`Sua próxima escolha será em ${nextWeekLabel()}.`);return false;}
  const item={...entry,kind:'weekly',ownerId:'me'};const selection={postId:item.id,item,weekKey:weekKey(),selectedAt:new Date().toISOString()};
  return await write('ressoa.weekly',selection);
 }
 const updated=[entry,...entries];return await write('ressoa.entries',updated,true,{clearDraft:true});
}
function mountStoryPreview() {
 if(page!=='foryou'||document.querySelector('dialog[open]'))return;
 const button=document.querySelector('.story[aria-hidden="false"] [data-play]');if(button)mountCoverPlayer(button,Number(button.dataset.play),stories[storyIndex]?.audioExcerpt);
}

async function loadLyrics(index) {
  lyricsRequest?.abort();
  const request = new AbortController(); lyricsRequest = request;
  const target = $('#lyrics-content'); if (!target) return;
  if (musicDetails[index].instrumental) { target.textContent = 'Esta gravação não possui letra.'; return; }
  target.textContent = 'Buscando letra…';
  try {
    const track = tracks[index], detail = musicDetails[index];
    const response = await fetch(`/api/lyrics?${new URLSearchParams({ title: track.title, artist: track.artist, album: track.album || '', duration: String(track.duration || detail.duration || 0) })}`, { signal: request.signal });
    if (!response.ok) throw new Error('lyrics');
    const data = await response.json();
    if (request.signal.aborted) return;
    target.replaceChildren();
    if (data.status === 'found' && typeof data.text === 'string') {
      const text = document.createElement('p'); text.className = 'lyrics-text'; text.textContent = data.text; target.append(text);
      const source = document.createElement('a'); source.className = 'lyrics-source'; source.href = 'https://lrclib.net'; source.textContent = 'Letra: LRCLIB ↗'; source.target = '_blank'; source.rel = 'noopener noreferrer'; target.append(source);
    } else target.textContent = data.status === 'instrumental' ? 'Gravação instrumental, sem letra.' : 'Letra não encontrada para esta gravação.';
  } catch (error) {
    if (error.name === 'AbortError') return;
    target.textContent = 'Letra indisponível no momento. ';
    const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'text-button'; retry.textContent = 'Tentar novamente'; retry.onclick = () => loadLyrics(index); target.append(retry);
  }
}

let musicIndex=null,musicGeneration=0;
function renderTrackContext(index) {
  const target=$('#track-context');if(!target||musicIndex!==index)return;
  const track=tracks[index],detail=musicDetails[index];
  const date=value=>/^\d{4}-\d{2}-\d{2}$/.test(value||'')?value.split('-').reverse().join('/'):'';
  const facts=[['Álbum',track.album],['Lançamento do álbum',date(detail.releaseDate)],['Duração',durationLabel(track.duration||detail.duration)],['Participantes',(detail.contributors||[]).join(', ')],['Edição da faixa',detail.trackReleaseDate!==detail.releaseDate?date(detail.trackReleaseDate):''],['Andamento',detail.bpm?`${detail.bpm} BPM`:''],['Conteúdo',detail.explicit?'Explícito':'']].filter(([,value])=>value);
  target.innerHTML=facts.length?`<h3>Sobre a gravação</h3><dl class="track-facts">${facts.map(([name,value])=>`<div><dt>${escape(name)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>`:'<p class="form-note">Dados adicionais indisponíveis para esta faixa.</p>';
  const heading=$('#music-content .music-heading .section-label');if(heading)heading.textContent=[track.year,track.album].filter(Boolean).join(' · ');
}
async function loadTrackContext(index,token) {
  try{await ensureTrackDetails(index);if(token===musicGeneration&&$('#music-dialog').open)renderTrackContext(index);}
  catch{
    if(token!==musicGeneration||!$('#music-dialog').open)return;
    const note=document.createElement('p');note.className='form-note';note.textContent='Não foi possível atualizar os dados da gravação. ';
    const retry=document.createElement('button');retry.type='button';retry.className='text-button';retry.textContent='Tentar novamente';retry.onclick=()=>{note.remove();loadTrackContext(index,token);};note.append(retry);$('#track-context')?.append(note);
  }
}
function openMusic(index) {
  if (!Number.isInteger(index) || !musicDetails[index]) return;
  const detail = musicDetails[index];
  const track = tracks[index];
  musicIndex=index;const token=++musicGeneration;
  $('#music-content').innerHTML = `<div class="music-heading"><img class="album-cover" src="${cover(index)}" alt="Capa de ${escape(track.album || track.title)}" width="150" height="150"><div><span class="section-label">${escape([track.year, track.album].filter(Boolean).join(' · '))}</span><h2 id="music-title">${escape(track.title)}</h2><p class="artist">${escape(track.artist)}</p>${spotifyBrand(index)}</div></div>
    <div class="music-player" data-preview-player></div>
    <section id="track-context" class="music-section" aria-live="polite"></section>
    ${detail.credits ? `<dl class="music-credits"><dt>Composição</dt><dd>${escape(detail.credits)}</dd></dl>` : ''}
    ${detail.history ? `<section class="music-section"><h3>História</h3><p>${escape(detail.history)}</p></section>` : '<p class="form-note">Contexto editorial ainda não disponível para esta faixa.</p>'}
    ${detail.meaning ? `<section class="music-section"><h3>Significado <span>· leitura editorial</span></h3><p>${escape(detail.meaning)}</p></section>` : ''}
    <details class="lyrics-section"><summary>Letra</summary><div id="lyrics-content" aria-live="polite"></div></details>
    ${detail.sources.length ? `<div class="music-sources"><h3>Fontes</h3>${detail.sources.map(source => `<a href="${escape(source.url)}" target="_blank" rel="noopener noreferrer">${escape(source.label)} ↗</a>`).join('')}</div>` : ''}`;
  $('#music-dialog').showModal();
  mountPreview($('#music-content [data-preview-player]'), index, 152);
  loadLyrics(index);
  renderTrackContext(index);if(detail.provider==='deezer')loadTrackContext(index,token);
}
document.addEventListener('click', event => {
  const music = event.target.closest('[data-music]');
  if (music && Date.now() - lastGesture >= 450) openMusic(Number(music.dataset.music));
});
$('#music-dialog').addEventListener('close', () => { musicGeneration++;musicIndex=null;lyricsRequest?.abort(); stopPreview(); $('#music-content').replaceChildren(); mountStoryPreview(); });
$('#composer').addEventListener('close', () => { composerPicker.close();entryAudio.stop(); stopPreview(); editingId = null; });
$('#weekly-dialog').addEventListener('close', () => { weeklyPicker.close();weeklyAudio.stop(); stopPreview(); });

let shortcutPhoto,shortcutName;
function updateProfileShortcut(){
 if(shortcutPhoto===profileInfo.photo&&shortcutName===profileInfo.displayName)return;
 shortcutPhoto=profileInfo.photo;shortcutName=profileInfo.displayName;
 $('.profile-shortcut').innerHTML=profileAvatar(shortcutPhoto,shortcutName);
}
function profileAvatar(photo = profileInfo.photo, name = profileInfo.displayName) {
  return `<span class="profile-avatar">${photo ? `<img src="${photo}" alt="Foto de ${escape(name)}">` : escape(name.slice(0, 2).toUpperCase())}</span>`;
}

function weeklyFeatureMarkup(post) {
 const own=isMine(post),title=escape(tracks[post.track].title),id=escape(post.id);
 const heading=own?title:`<button type="button" class="track-name weekly-title-open" data-read="${id}" aria-label="Abrir ressoa da semana: ${title}">${title}</button>`;
 const actions=own?'':`<div class="weekly-social" role="group" aria-label="Ações do ressoa da semana">${socialButtons(post)}${saveButton(post)}</div>`;
 const menu=own?`<details class="weekly-menu options-menu"><summary class="icon-button" aria-label="Opções do ressoa da semana" title="Opções do ressoa da semana"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none"/></svg></summary><div class="weekly-menu-panel options-menu-panel" role="group" aria-label="Ações do seu destaque semanal"><button type="button" data-read="${id}">Abrir</button><button type="button" data-share="${id}">Compartilhar</button><button type="button" data-delete-weekly>Apagar</button></div></details>`:'';
 return `<section class="profile-weekly weekly-feature" style="--weekly-art:url(${escape(JSON.stringify(cover(post.track)))})"><span class="section-label">Ressoa da semana</span>${menu}<div class="weekly-feature-body"><div>${playableArt(post.track,220,post.lyricExcerpt,post)}${spotifyBrand(post.track)}</div><div>${own?authorMarkup(post):''}<h2 class="track-title">${heading}</h2><p class="weekly-reflection${post.text?'':' no-comment'}">${escape(previewText(post))}</p>${actions}</div></div></section>`;
}
document.addEventListener('click',event=>{
 const chosen=event.target.closest('.options-menu-panel button');
 document.querySelectorAll('.options-menu[open]').forEach(menu=>{
  if(chosen&&menu.contains(chosen)){menu.open=false;menu.querySelector('summary').focus({preventScroll:true});}
  else if(!menu.contains(event.target))menu.open=false;
 });
},true);
document.addEventListener('keydown',event=>{
 if(event.key!=='Escape')return;
 const menu=document.querySelector('.options-menu[open]');if(!menu)return;
 event.preventDefault();menu.open=false;menu.querySelector('summary').focus({preventScroll:true});
});
function applyProfileBackground() {
 const info=visitedId?visitedProfile?.profile:profileInfo;
 const has=page==='perfil'&&Number.isInteger(info?.background)&&tracks[info.background];
 document.body.classList.toggle('profile-background',Boolean(has));
 if(has)document.body.style.setProperty('--profile-art',`url(${JSON.stringify(cover(info.background))})`);else document.body.style.removeProperty('--profile-art');
}
function renderProfile() {
 const own=!visitedId,info=own?profileInfo:visitedProfile?.profile;
 const relationOwner=own?getAccount().user.id:visitedId;
 const canRelations=own||visitedProfile?.canViewRelations===true;
 $('#profile-options').innerHTML=info&&canRelations?`<details class="profile-menu options-menu"><summary class="icon-button" aria-label="Opções do perfil" title="Opções do perfil">${icons.more}</summary><div class="profile-menu-panel options-menu-panel" role="group" aria-label="Conexões do perfil"><button type="button" data-followers-list="${escape(relationOwner)}">Seguidores</button><button type="button" data-following-list="${escape(relationOwner)}">Seguindo</button></div></details>`:'';
 $('#edit-profile').hidden=!own;$('#logout').hidden=!own;$('#back-my-profile').hidden=own;
 $('#profile-label').textContent=own?'Meu perfil':'Perfil';
 if(!info){
  $('#profile-content').innerHTML=`<div class="empty" role="status"><p>${escape(profileError||'Carregando perfil…')}</p>${profileError?'<button class="text-button" data-retry-profile>Tentar novamente</button>':''}</div>`;
  applyProfileBackground();return;
 }
 const publicEntries=own?entries.filter(post=>post.visibility==='public'):visitedProfile.entries;
 const featured=own?myWeeklyPost():visitedProfile.weekly;
 const reposted=own?feedPosts().filter(post=>post.visibility!=='private'&&social.reposts.includes(post.id)):visitedProfile.reposts;
 const repostIds=new Set(reposted.map(post=>post.id)),combined=[...new Map([...publicEntries,...reposted].map(post=>[post.id,post])).values()];
 const ordered=combined.sort((a,b)=>Number(info.pinned.includes(b.id))-Number(info.pinned.includes(a.id))||Date.parse(b.createdAt)-Date.parse(a.createdAt)||b.id.localeCompare(a.id));
 const more=(kind,next)=>!own&&next!==null?`<button class="button load-profile-posts" data-more-profile="${kind}" ${loadingMore?'disabled':''}>${loadingMore?'Carregando…':kind==='reposts'?'Carregar mais reposts':'Carregar mais'}</button>`:'';
 const identity=`<div class="profile-identity">${profileAvatar(info.photo,info.displayName)}<div><h1>${escape(info.displayName)}</h1><p class="profile-handle">@${escape(info.handle)}</p>${info.bio?`<p class="profile-bio">${escape(info.bio)}</p>`:''}${own?'':`<button class="button profile-follow" data-follow="${escape(visitedId)}" data-private="${Boolean(info.isPrivate)}" ${pendingAttributes('follow',visitedId)} aria-pressed="${hasFollow(visitedId)}">${followLabel(visitedId,info.isPrivate)}</button>`}</div></div>`;
 if(!own&&visitedProfile.canView===false){$('#profile-content').innerHTML=identity+'<section class="locked-profile"><h2>Perfil privado</h2><p>Somente seguidores aprovados.</p></section>';applyProfileBackground();return;}
 $('#profile-content').innerHTML=`${identity}
 ${featured?weeklyFeatureMarkup(featured):''}
 ${info.favorites.length?`<section class="profile-favorites"><h2>Favoritas</h2><div class="favorite-grid">${info.favorites.map(index=>`<div>${trackArt(index,180)}<p><button class="track-name" data-music="${index}">${escape(tracks[index].title)}</button></p><span class="artist">${escape(tracks[index].artist)}</span>${spotifyBrand(index)}</div>`).join('')}</div></section>`:''}
 <section class="profile-posts" aria-label="Ressoas"><div class="diary-grid">${ordered.length?ordered.map(post=>diaryMarkup(post,{reposted:repostIds.has(post.id),pinned:info.pinned.includes(post.id),inProfile:true})).join(''):'<p class="empty">Nenhuma ressoa.</p>'}</div><div class="profile-pagination">${more('entries',visitedProfile?.nextEntriesOffset)}${more('reposts',visitedProfile?.nextRepostsOffset)}</div></section>`;
 applyProfileBackground();
 scheduleTextLayout();
}
async function loadVisitedProfile() {
 if(!visitedId||(profileRequest&&!profileRequest.signal.aborted))return;
 const id=visitedId,token=++profileGeneration;
 profileRequest=new AbortController();profileError='';loadingMore=false;renderProfile();
 try {
  const data=await api(`/api/profile?${new URLSearchParams({user:id})}`,{signal:profileRequest.signal});
  if(token!==profileGeneration||visitedId!==id)return;
  visitedProfile=hydratePublicProfile(data);renderProfile();
 }catch(error){if(error.name!=='AbortError'&&token===profileGeneration){profileError=error.status===404?'Esse perfil não foi encontrado.':'Não foi possível carregar o perfil. Tente novamente.';visitedProfile=null;renderProfile();}}
 finally{if(token===profileGeneration)profileRequest=null;}
}
async function loadMoreProfile(kind) {
 if(loadingMore||!visitedProfile||profileRequest)return;
 const key=kind==='reposts'?'nextRepostsOffset':'nextEntriesOffset',offset=visitedProfile[key];if(offset===null)return;
 const id=visitedId,token=++profileGeneration;loadingMore=true;profileRequest=new AbortController();renderProfile();
 const params=new URLSearchParams({user:id,[kind==='reposts'?'repostOffset':'offset']:String(offset)});
 try {
  const data=hydratePublicProfile(await api(`/api/profile?${params}`,{signal:profileRequest.signal}));
  if(token!==profileGeneration||visitedId!==id)return;
  if(data.canView===false){visitedProfile=data;return;}
  visitedProfile[kind]=[...new Map([...visitedProfile[kind],...data[kind]].map(post=>[post.id,post])).values()];visitedProfile[key]=data[key];
 }catch(error){if(error.name!=='AbortError')toast('Não foi possível carregar mais ressoas. Tente novamente.');}
 finally{if(token===profileGeneration){loadingMore=false;profileRequest=null;renderProfile();}}
}
async function togglePin(id) {
 if(!entries.some(post=>post.id===id&&post.visibility==='public'))return;
 const pinned=profileInfo.pinned.includes(id)?profileInfo.pinned.filter(value=>value!==id):[...profileInfo.pinned,id];
 const updated={...profileInfo,pinned};if(!await write('ressoa.profile',updated))return;renderProfile();renderDiary();if($('#reader').open)openPost(id);toast(pinned.includes(id)?'Fixada no perfil.':'Ressoa desafixada.');
}

$('#diary-entries').addEventListener('click', event => {
  const pin = event.target.closest('[data-pin]');
  if (pin) togglePin(pin.dataset.pin);
});
$('#profile-content').addEventListener('click', event => {
  if(event.target.closest('[data-retry-profile]'))loadVisitedProfile();
  const more=event.target.closest('[data-more-profile]');if(more)loadMoreProfile(more.dataset.moreProfile);
  const readButton = event.target.closest('[data-read]');
  const pin = event.target.closest('[data-pin]');
  const feature = event.target.closest('[data-weekly]');
  if (readButton) openPost(readButton.dataset.read);
  if (pin) togglePin(pin.dataset.pin);
  if (feature) setWeekly(feature.dataset.weekly);
});

const profileForm = $('#profile-form');
bindUsernameValidation(profileForm.elements.handle);
let pendingPhoto = '';
let pendingBackground = null;
const backgroundPicker = createTrackPicker($('#background-track-picker'), { ...pickerOptions, onChange: index => { pendingBackground = index; } });
$('#remove-background').addEventListener('click', () => { pendingBackground = null; backgroundPicker.reset(); });
let photoBusy = false;
$('#choose-photo').addEventListener('click', () => $('#profile-photo').click());
function renderFavoriteOptions() {
  if(favoritePickers.length)return;
  $('#favorite-fields').innerHTML='<legend>Músicas favoritas · até 6</legend>'+Array.from({length:6},(_,slot)=>`<div class="favorite-picker track-picker" id="favorite-picker-${slot}"></div>`).join('')+'<p id="favorite-error" class="form-note" role="alert"></p>';
  for(let slot=0;slot<6;slot++)favoritePickers.push(createTrackPicker($(`#favorite-picker-${slot}`),{
    label:`Favorita ${slot+1}`,onError:toast,onChange:()=>{favoritePickers.forEach(picker=>picker.input.setCustomValidity(''));$('#favorite-error').textContent='';}
  }));
}
const favoritePickers=[];
$('#edit-profile').addEventListener('click', () => {
  pendingBackground = profileInfo.background;
  backgroundPicker.reset();
  if (Number.isInteger(pendingBackground)) backgroundPicker.setSelection(pendingBackground, false);
  renderFavoriteOptions();
  profileForm.elements.displayName.value = profileInfo.displayName;
  profileForm.elements.handle.value = profileInfo.handle;
  profileForm.elements.handle.setCustomValidity('');
  profileForm.elements.bio.value = profileInfo.bio;
  profileForm.elements.isPrivate.checked=profileInfo.isPrivate;
  for (let i = 0; i < 6; i++) {
    favoritePickers[i].reset();favoritePickers[i].input.setCustomValidity('');
    if(Number.isInteger(profileInfo.favorites[i]))favoritePickers[i].setSelection(profileInfo.favorites[i],false);
  }
  $('#favorite-error').textContent='';
  pendingPhoto = profileInfo.photo;
  $('#photo-preview').innerHTML = profileAvatar(pendingPhoto);
  $('#profile-photo').value = '';
  $('#profile-editor').showModal();
});
$('#remove-photo').addEventListener('click', () => {
  pendingPhoto = '';
  $('#photo-preview').innerHTML = profileAvatar('');
});
$('#profile-photo').addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 2 * 1024 * 1024) {
    toast('Use uma imagem JPG, PNG ou WebP de até 2 MB.'); return;
  }
  photoBusy = true;
  profileForm.querySelector('[type="submit"]').disabled = true;
  const url = URL.createObjectURL(file);
  try {
    const image = new Image(); image.src = url; await image.decode();
    const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 256;
    const ctx = canvas.getContext('2d'); const side = Math.min(image.naturalWidth, image.naturalHeight);
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 256, 256);
    ctx.drawImage(image, (image.naturalWidth - side) / 2, (image.naturalHeight - side) / 2, side, side, 0, 0, 256, 256);
    pendingPhoto = canvas.toDataURL('image/jpeg', .85);
    $('#photo-preview').innerHTML = profileAvatar(pendingPhoto);
  } catch { toast('Não foi possível abrir essa imagem.'); }
  finally { URL.revokeObjectURL(url); photoBusy = false; profileForm.querySelector('[type="submit"]').disabled = false; }
});
profileForm.addEventListener('submit', async event => {
  event.preventDefault(); if (photoBusy || savingProfile) return;
  const name = profileForm.elements.displayName.value.trim();
  if (name.length < 2) { profileForm.elements.displayName.setCustomValidity('Use ao menos duas letras.'); profileForm.elements.displayName.reportValidity(); return; }
  const values=favoritePickers.map(picker=>picker.value).filter(value=>value!==null);
  if(new Set(values).size!==values.length){$('#favorite-error').textContent='Escolha músicas diferentes para suas favoritas.';favoritePickers[0].input.focus();return;}
  const updated = cleanProfile({ ...profileInfo, displayName: name, handle: profileForm.elements.handle.value.trim(), bio: profileForm.elements.bio.value.trim(), favorites: values.map(Number), photo: pendingPhoto, background: pendingBackground,isPrivate:profileForm.elements.isPrivate.checked });
  savingProfile=true;
  const submit=profileForm.querySelector('[type="submit"]'),submitLabel=submit.textContent;submit.disabled=true;submit.textContent='Salvando…';submit.setAttribute('aria-busy','true');
  let stored;
  try { stored=await write('ressoa.profile',updated); }
  finally { savingProfile=false;submit.disabled=false;submit.textContent=submitLabel;submit.removeAttribute('aria-busy'); }
  if(!stored)return;
  $('#profile-editor').close();
  renderProfile(); renderDiary(); renderStories(); toast('Perfil salvo.');
});
profileForm.elements.displayName.addEventListener('input', event => event.target.setCustomValidity(''));


function followButton(post) {
 const owner=isMine(post)?'me':authorKey(post);if(owner==='me')return '';
 return `<button class="follow-button" data-follow="${escape(owner)}" data-private="${Boolean(post.authorPrivate)}" ${pendingAttributes('follow',owner)} aria-pressed="${hasFollow(owner)}">${followLabel(owner,post.authorPrivate)}</button>`;
}
const hasFollow=id=>social.following.includes(id)||(social.requested||[]).includes(id);
const followLabel=(id,privateProfile)=>social.following.includes(id)?'Seguindo':(social.requested||[]).includes(id)?'Solicitado':privateProfile?'Solicitar seguir':'Seguir';
function updatePrivacyUI() {
 $('#entry-form [value="public"]').textContent=profileInfo.isPrivate?'Seguidores':'Pública';
}
function socialButtons(post) {
 const commentButton=`<button type="button" class="icon-button social-action" data-comments="${escape(post.id)}" aria-label="Ver comentários">${svg('<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-3 3V11.5A8.5 8.5 0 0 1 9.5 3h3a8.5 8.5 0 0 1 8.5 8.5Z"/>')}</button>`;
 if(post.visibility==='private')return commentButton;
 const liked=(social.likes[post.id]||[]).includes('me'),reposted=social.reposts.includes(post.id);
 return `<button class="icon-button social-action like-action" data-like="${escape(post.id)}" ${pendingAttributes('like',post.id)} aria-label="${liked?'Descurtir':'Curtir'} ressoa" aria-pressed="${liked}">${svg('<path d="M20.8 4.8a5.5 5.5 0 0 0-7.8 0L12 5.9l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.4a5.5 5.5 0 0 0 0-7.8Z"/>')}</button>${commentButton}${!isMine(post)?`<button class="icon-button social-action" data-repost="${escape(post.id)}" ${pendingAttributes('repost',post.id)} aria-label="${reposted?'Remover repost':'Repostar ressoa'}" aria-pressed="${reposted}">${svg('<path d="m16 3 4 4-4 4M4 11V7h16M8 21l-4-4 4-4m12 0v4H4"/>')}</button>`:''}<button class="icon-button social-action" data-share="${escape(post.id)}" aria-label="Compartilhar ressoa">${svg('<path d="M12 16V3m-4 4 4-4 4 4M5 13v7h14v-7"/>')}</button>`;
}
function syncSocialButtons() {
 const markPending=(button,kind,target)=>{const waiting=actionPending(kind,target);button.disabled=waiting;if(waiting)button.setAttribute('aria-busy','true');else button.removeAttribute('aria-busy');};
 document.querySelectorAll('[data-like]').forEach(button=>{const on=(social.likes[button.dataset.like]||[]).includes('me');button.setAttribute('aria-pressed',String(on));button.setAttribute('aria-label',on?'Descurtir ressoa':'Curtir ressoa');markPending(button,'like',button.dataset.like);});
 document.querySelectorAll('[data-repost]').forEach(button=>{const on=social.reposts.includes(button.dataset.repost);button.setAttribute('aria-pressed',String(on));button.setAttribute('aria-label',on?'Remover repost':'Repostar ressoa');markPending(button,'repost',button.dataset.repost);});
 document.querySelectorAll('[data-save]').forEach(button=>{const on=saved.includes(button.dataset.save),post=allPosts().find(post=>post.id===button.dataset.save);button.setAttribute('aria-pressed',String(on));if(post)button.setAttribute('aria-label',`${on?'Remover das':'Adicionar às'} guardadas: ${tracks[post.track].title}`);markPending(button,'saved',button.dataset.save);});
 document.querySelectorAll('[data-follow]').forEach(button=>{const id=button.dataset.follow;button.setAttribute('aria-pressed',String(hasFollow(id)));button.textContent=button.hasAttribute('data-follow-back')&&!hasFollow(id)?'Seguir de volta':button.closest('#people-dialog')&&peopleMode==='following'&&social.following.includes(id)?'Deixar de seguir':followLabel(id,button.dataset.private!=='false');markPending(button,'follow',id);});
}
function pendingAttributes(kind,target){return actionPending(kind,target)?'disabled aria-busy="true"':'';}
let peopleRequest=null,peopleGeneration=0,peopleMode=null;
function cancelPeopleRequest() {peopleRequest?.abort();peopleRequest=null;peopleGeneration++;}
$('#people-dialog').addEventListener('close',()=>{cancelPeopleRequest();peopleMode=null;});
async function showInteractions(id) {
 const post=allPosts().find(item=>item.id===id);if(!post||!isMine(post))return;
 cancelPeopleRequest();peopleMode='interactions';const token=peopleGeneration,request=new AbortController();peopleRequest=request;
 $('#people-title').textContent='Curtidas e reposts';
 $('#people-content').textContent='Carregando…';if(!$('#people-dialog').open)$('#people-dialog').showModal();
 try {
  const {people}=await api(`/api/interactions?${new URLSearchParams({post:id})}`,{signal:request.signal});
  if(token!==peopleGeneration||!$('#people-dialog').open)return;
  $('#people-content').innerHTML=people.length?people.map(person=>`<div class="person-row"><a class="person-link person-identity" href="${escape(personHref(person.id))}" data-person="${escape(person.id)}">${profileAvatar(person.photo,person.displayName)}<span>${escape(person.displayName)}<small>@${escape(person.handle)}</small><small class="interaction-label">${[person.liked?'Curtiu':'',person.reposted?'Repostou':''].filter(Boolean).join(' · ')}</small></span></a></div>`).join(''):'<p class="empty">Nenhuma interação ainda.</p>';
 }catch(error){if(error.name!=='AbortError'&&token===peopleGeneration)$('#people-content').textContent=error.message;}
 finally{if(token===peopleGeneration)peopleRequest=null;}
}
async function showRelations(kind,target=getAccount().user.id){
 cancelPeopleRequest();peopleMode=kind;
 const own=target===getAccount().user.id,token=peopleGeneration;
 $('#people-title').textContent=kind==='following'?'Seguindo':'Seguidores';
 $('#people-content').textContent='Carregando…';if(!$('#people-dialog').open)$('#people-dialog').showModal();
 let people;
 try{
  if(own)people=kind==='following'?getAccount().followingPeople:getAccount().followersPeople;
  else{peopleRequest=new AbortController();({people}=await api(`/api/connections?${new URLSearchParams({user:target,kind})}`,{signal:peopleRequest.signal}));}
  if(token!==peopleGeneration||!$('#people-dialog').open)return;
  $('#people-content').innerHTML=people?.length?people.map(person=>`<div class="person-row">${peopleIdentity(person)}${own?(kind==='following'?`<button class="text-button" data-follow="${escape(person.id)}" aria-pressed="true">Deixar de seguir</button>`:`<button class="text-button" data-remove-follower="${escape(person.id)}">Remover</button>`):''}</div>`).join(''):`<p class="empty">${kind==='following'?(own?'Você ainda não segue ninguém.':'Não segue ninguém ainda.'):'Nenhum seguidor.'}</p>`;
 }catch(error){if(error.name!=='AbortError'&&token===peopleGeneration)$('#people-content').textContent=error.message;}
 finally{if(token===peopleGeneration)peopleRequest=null;}
}
const showFollowing=target=>showRelations('following',target);
const showFollowers=target=>showRelations('followers',target);
function peopleIdentity(person) {
 return `<a class="person-link person-identity" href="${escape(personHref(person.id))}" data-person="${escape(person.id)}">${profileAvatar(person.photo,person.displayName)}<span>${escape(person.displayName)}<small>@${escape(person.handle)}</small></span></a>`;
}
const comments=createComments({identity:peopleIdentity,toast,stopPreview});
document.addEventListener('click',event=>{const button=event.target.closest('[data-comments]');if(button)comments.open(button.dataset.comments);});
const notifications=createNotifications({
 identity:peopleIdentity,toast,
 onComment:id=>comments.open(id),
 onResponse:()=>{if(page==='perfil'&&!visitedId)renderProfile();},
 onFollowChange:()=>{if(page==='perfil'&&visitedId)void loadVisitedProfile();else void refreshView();},
 followButton:person=>`<button type="button" class="button" data-follow-back data-follow="${escape(person.id)}" data-private="${Boolean(person.isPrivate)}" ${pendingAttributes('follow',person.id)} aria-pressed="${hasFollow(person.id)}">${hasFollow(person.id)?followLabel(person.id,person.isPrivate):'Seguir de volta'}</button>`
});
function askDelete(title,message,action,label='Apagar') {
 confirmAction=action;$('#confirm-title').textContent=title;$('#confirm-message').textContent=message;$('#confirm-action').textContent=label;$('#confirm-dialog').showModal();
}
$('#confirm-action').addEventListener('click',()=>{const action=confirmAction;confirmAction=null;$('#confirm-dialog').close();action?.();});
function removeEntry(id) {
 const post=entries.find(item=>item.id===id);if(!post)return;
 askDelete('Apagar ressoa?','Este registro será removido do seu diário e perfil.',async()=>{
  const updated=entries.filter(item=>item.id!==id);if(!await write('ressoa.entries',updated))return;
  if(readerId===id)$('#reader').close();renderStories();renderDiary();renderProfile();toast('Ressoa apagada.');
 });
}
function removeWeekly() {
 if(!myWeeklyPost())return;
 askDelete('Apagar destaque da semana?',`Você poderá escolher outro somente em ${nextWeekLabel()}, à 0h de Brasília. O diário não será alterado.`,async()=>{
  const record={...weekly,item:null,deletedAt:new Date().toISOString()};if(!await write('ressoa.weekly',record))return;
  if(readerId===record.postId)$('#reader').close();renderStories();renderDiary();renderProfile();toast('Destaque apagado. A escolha da semana continua usada.');
 });
}
$('#delete-weekly').addEventListener('click',removeWeekly);
let shareGeneration=0,sharePreviewUrl='';
function clearSharePreview(){
 $('#share-preview').replaceChildren();
 if(sharePreviewUrl)URL.revokeObjectURL(sharePreviewUrl);sharePreviewUrl='';
}
async function openShare(id) {
 const post=linkedPost?.id===id?linkedPost:allPosts().find(item=>item.id===id);if(!post||post.visibility==='private')return;
 const token=++shareGeneration;sharePost=post;shareFile=null;clearSharePreview();
 $('#share-status').textContent='Preparando ressoa…';$('#download-share').disabled=true;$('#share-dialog').showModal();
 try{
  const blob=await createShareImage({post,track:tracks[post.track],artwork:cover(post.track),author:authorHandle(post),photo:isMine(post)?profileInfo.photo:post.photo,initials:isMine(post)?profileInfo.displayName.slice(0,2).toUpperCase():post.initials,provider:musicDetails[post.track].provider});
  if(token!==shareGeneration)return;
  if(!blob)throw new Error('Image unavailable');
  shareFile=blob;sharePreviewUrl=URL.createObjectURL(blob);
  const image=document.createElement('img');image.src=sharePreviewUrl;image.alt='Prévia do ressoa para baixar';$('#share-preview').append(image);
  $('#download-share').disabled=false;$('#share-status').textContent='';
 }catch{if(token===shareGeneration)$('#share-status').textContent='Não foi possível preparar a imagem. Você ainda pode copiar o link.';}
}
const shareUrl = () => sharePost?new URL(`/#ressoa/${encodeURIComponent(sharePost.id)}`,location.origin).href:'';
$('#download-share').addEventListener('click',()=>{if(shareFile)downloadFile(shareFile,'ressoa-card.png');});
$('#copy-share-link').addEventListener('click',async()=>{try{if(sharePost){await navigator.clipboard.writeText(shareUrl());toast('Link copiado.');}}catch{toast('O navegador não permitiu copiar o link.');}});
$('#share-dialog').addEventListener('close',()=>{shareGeneration++;shareFile=null;sharePost=null;clearSharePreview();});
$('#profile-editor').addEventListener('close',()=>{backgroundPicker.close();favoritePickers.forEach(picker=>picker.close());stopPreview();});
document.addEventListener('click',async event=>{
 const play=event.target.closest('[data-play]');if(play){const post=allPosts().find(item=>item.id===play.dataset.playPost);toggleCoverPlayer(play,Number(play.dataset.play),event,post?.audioExcerpt);return;}
 if(event.target.closest('[data-person]'))document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
 const like=event.target.closest('[data-like]'),follow=event.target.closest('[data-follow]'),repost=event.target.closest('[data-repost]'),share=event.target.closest('[data-share]');
 const edit=event.target.closest('[data-edit]'),del=event.target.closest('[data-delete]'),feature=event.target.closest('[data-feature]'),pin=event.target.closest('[data-reader-pin]'),interactionList=event.target.closest('[data-interactions]');
 if(like||follow||repost){
  const button=like||follow||repost;if(button.disabled)return;button.disabled=true;button.setAttribute('aria-busy','true');
  try{
   if(like){const post=allPosts().find(item=>item.id===like.dataset.like);if(!post||post.visibility==='private'||actionPending('like',post.id))return;await socialAction('like',post.id,!(social.likes[post.id]||[]).includes('me'),{post});}
   if(follow){const id=follow.dataset.follow;if(id==='me'||actionPending('follow',id))return;await socialAction('follow',id,!hasFollow(id),{privateProfile:follow.dataset.private!=='false'});renderStories();if(page==='perfil'){if(visitedId)await loadVisitedProfile();else renderProfile();}if($('#people-dialog').open&&peopleMode==='following')showFollowing();}
   if(repost){const post=allPosts().find(item=>item.id===repost.dataset.repost);if(!post||isMine(post)||post.visibility==='private'||actionPending('repost',post.id))return;await socialAction('repost',post.id,!social.reposts.includes(post.id),{post});if(page==='perfil')renderProfile();toast(social.reposts.includes(post.id)?'Repostado no seu perfil.':'Repost removido.');}
  }catch(error){toast(error.message);}finally{button.disabled=false;button.removeAttribute('aria-busy');syncSocialButtons();}
 }
 if(share)openShare(share.dataset.share);
 if(edit){$('#reader').close();openComposer(edit.dataset.edit);}
 if(del)removeEntry(del.dataset.delete);
 if(feature)setWeekly(feature.dataset.feature);
 if(pin)togglePin(pin.dataset.readerPin);
 if(interactionList)showInteractions(interactionList.dataset.interactions);
 if(event.target.closest('[data-delete-weekly]'))removeWeekly();
 const followingList=event.target.closest('[data-following-list]'),followersList=event.target.closest('[data-followers-list]');
 if(followingList)showFollowing(followingList.dataset.followingList||undefined);
 if(followersList)showFollowers(followersList.dataset.followersList||undefined);
 const remove=event.target.closest('[data-remove-follower]');
 if(remove){
  const control=remove;control.disabled=true;control.setAttribute('aria-busy','true');
  try {
   await mutate('/api/follower','DELETE',{user:remove.dataset.removeFollower});
   renderStories();if(page==='perfil')renderProfile();
   void notifications.refresh();if(peopleMode==='followers')showFollowers();
  }catch(error){toast(error.message);}finally{control.disabled=false;control.removeAttribute('aria-busy');}
 }
});

let displayedWeek = weekKey();
async function refreshWeek() {
  if (displayedWeek !== weekKey()&&await refreshView()) displayedWeek = weekKey();
}
setInterval(() => {refreshWeek();if(stories.some(post=>!isInFeed(post))&&!document.querySelector('dialog[open]'))renderStories(false,true);},60000);
document.addEventListener('visibilitychange', refreshWeek);
window.addEventListener('accountchange', () => {
 const oldReposts=social.reposts,oldSaved=saved,oldFollowing=social.following;
 entries = validEntries(read('ressoa.entries', [])); saved=read('ressoa.saved',[]);
 profileInfo=cleanProfile(read('ressoa.profile',defaultProfile));social=read('ressoa.social',{});
 weekly=read('ressoa.weekly',null);publicPosts=read('ressoa.public',[]);
 updatePrivacyUI();updateProfileShortcut();
 if(page==='foryou'&&feedMode==='following'&&JSON.stringify(oldFollowing)!==JSON.stringify(social.following))renderStories(false,true);
 if(page==='perfil'&&!visitedId&&JSON.stringify(oldReposts)!==JSON.stringify(social.reposts))renderProfile();
 if(page==='diario'&&collection==='saved'&&JSON.stringify(oldSaved)!==JSON.stringify(saved))renderDiary();
 syncSocialButtons();
 $('#account-status').textContent=`@${getAccount().user.username}`;
});

$('#logout').addEventListener('click', async () => {
 clearTimeout(draftTimer);stopPreview();$('#logout').disabled=true;
 try { await mutate('/api/logout','POST',{}); location.replace('/'); }
 catch(error){toast(error.message);$('#logout').disabled=false;}
});
async function refreshView(reset=false) {
 if(document.querySelector('dialog[open]')||busy())return false;
 try{if(await refreshAccount()){feedGeneratedAt=Date.now();renderStories(reset,true);if(page==='diario')renderDiary();if(page==='perfil'){if(visitedId)await loadVisitedProfile();else renderProfile();}return true;}}catch(error){toast(error.message);}return false;
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshView();});
window.addEventListener('accountentered',()=>{route();mountStoryPreview();});
$('#account-status').textContent=`@${getAccount().user.username}`;
updatePrivacyUI();updateProfileShortcut();

renderStories();
route();

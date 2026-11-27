import { api, getAccount } from './session.js';
import { registerTrack } from './catalog-store.js';
import { newId } from './id.js';
import { albumArt, fitLyricArt } from './post-art.js';

const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const stamp=value=>new Date(value).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
const clock=value=>new Date(value).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
const inboxTime=value=>new Date(value).toDateString()===new Date().toDateString()?clock(value):new Date(value).toLocaleDateString('pt-BR',{day:'2-digit',month:'2-digit'});
const unreadLabel=count=>count>4?'+4':String(count);
const emptyIcon='<svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="19"/><circle cx="24" cy="24" r="6"/><circle cx="24" cy="24" r="2"/><path d="M10 24a14 14 0 0 1 14-14m0 28a14 14 0 0 0 14-14"/></svg>';
const reactionEmojis=[['❤️','Coração'],['👍','Joia'],['😂','Rindo'],['😮','Surpresa'],['🔥','Fogo'],['🥲','Sorrindo com lágrima'],['😍','Apaixonado'],['🥰','Carinho'],['😊','Sorriso'],['😁','Felicidade'],['😎','Estiloso'],['🤩','Encantado'],['😭','Chorando'],['😢','Triste'],['😅','Sorriso sem graça'],['🤣','Rindo muito'],['🤔','Pensando'],['👀','De olho'],['🙌','Celebrando'],['👏','Palmas'],['🤝','Aperto de mãos'],['💪','Força'],['🙏','Agradecimento'],['👌','Perfeito'],['💯','Cem por cento'],['✨','Brilho'],['🎉','Festa'],['🎵','Nota musical'],['🎶','Notas musicais'],['🎧','Fones'],['💿','Disco'],['🖤','Coração preto'],['💜','Coração roxo'],['💙','Coração azul'],['🤍','Coração branco'],['💔','Coração partido'],['🫶','Coração com as mãos']];
const smileIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M8 14a4.5 4.5 0 0 0 8 0M8.5 9h.01M15.5 9h.01"/></svg>';

export function createMessages({ toast, stopPreview, onCompose, onPlay, onOpenPost }) {
  const $=selector=>document.querySelector(selector);
  const dialog=$('#messages-dialog'),badge=$('#message-count'),button=$('#messages-button');
  const inbox=$('#messages-inbox'),chat=$('#messages-chat'),thread=$('#messages-thread'),status=$('#messages-status');
  const search=$('#messages-search'),results=$('#messages-people'),list=$('#messages-conversations');
  const form=$('#message-form'),input=form.elements.text,send=form.querySelector('[type=submit]');
  const back=$('#messages-back'),older=$('#messages-older'),more=$('#messages-more');
  const reactionDialog=$('#message-reaction-dialog'),reactionQuick=$('#message-reaction-quick'),reactionMore=$('#message-reaction-more');
  let owner=getAccount().user.id,summary={version:-1,unreadCount:0},person=null,items=[],conversations=[],cursor=null,inboxCursor=null;
  let request,searchRequest,generation=0,searchTimer,polling=false,sending=false,lastPoll=0,loadedVersion=-1,pendingPost=null,pendingShareId=null,submission=null;
  const drafts=new Map(),visible=new Set(),conversationCache=new Map(),conversationJobs=new Map();let reading=false,readTimer;
  let inboxLoaded=false,inboxVersion=-1,inboxJob=null,cacheEpoch=0;
  const reactionJobs=new Map(),reactionChanges=new Map(),readCounts=new Map();let reactionTarget=null;
  let pendingRead=null;
  const self=()=>getAccount().user.id;
  const observer=new IntersectionObserver(entries=>{
    if(!dialog.open||document.hidden)return;
    for(const entry of entries){const id=entry.target.dataset.message;if(entry.isIntersecting)visible.add(id);else visible.delete(id);}
    clearTimeout(readTimer);readTimer=setTimeout(readVisible,250);
  },{root:thread,threshold:0});

  function updateSummary(value){
    if(!value||value.version<summary.version)return;
    summary=value;badge.hidden=!value.unreadCount;badge.textContent=unreadLabel(value.unreadCount);
    button.setAttribute('aria-label',value.unreadCount?`Mensagens: ${value.unreadCount} novidades não lidas`:'Mensagens');
  }
  function resetRequest(){request?.abort();request=null;generation++;status.textContent='';}
  function reconcileReactions(message,version){
    const changed=reactionChanges.get(message.id);
    if(changed&&version<changed.version)message.reactions=changed.reactions;
    else if(changed)reactionChanges.delete(message.id);
    return message;
  }
  function rememberConversation(data){
    data.items.forEach(item=>reconcileReactions(item,data.summary.version));
    conversationCache.delete(data.person.id);
    conversationCache.set(data.person.id,{...data,items:[...data.items],savedAt:Date.now()});
    if(conversationCache.size>20)conversationCache.delete(conversationCache.keys().next().value);
  }
  function fetchInbox(){
    if(inboxJob)return inboxJob.promise;
    const account=owner,epoch=cacheEpoch,controller=new AbortController(),job={controller};
    inboxJob=job;
    job.promise=api('/api/messages',{signal:controller.signal}).then(data=>{
      if(account!==self()||epoch!==cacheEpoch)return;
      for(const item of data.items){const read=readCounts.get(item.person.id);if(!read)continue;
        if(data.summary.version<read.version)item.unreadCount=read.count;else readCounts.delete(item.person.id);}
      conversations=data.items;inboxCursor=data.nextCursor;inboxLoaded=true;inboxVersion=data.summary.version;
      updateSummary(data.summary);
      const recent=data.items[0]?.person.id,cached=conversationCache.get(recent);
      if(!dialog.open&&recent&&(!cached||Date.now()-cached.savedAt>=300000))void fetchConversation(recent).catch(()=>{});
      return data;
    }).finally(()=>{if(inboxJob===job)inboxJob=null;});
    return job.promise;
  }
  function fetchConversation(target){
    if(conversationJobs.has(target))return conversationJobs.get(target).promise;
    const account=owner,epoch=cacheEpoch,controller=new AbortController(),job={controller};
    conversationJobs.set(target,job);
    const watched=person?.id===target?[...visible].slice(0,50):[];
    job.promise=api('/api/messages?'+new URLSearchParams({user:target,...(watched.length?{reactions:watched.join(',')}:{})}),{signal:controller.signal}).then(data=>{
      if(account===self()&&epoch===cacheEpoch&&data.summary.version>=(conversationCache.get(target)?.summary.version??-1))rememberConversation(data);
      return data;
    }).finally(()=>{if(conversationJobs.get(target)===job)conversationJobs.delete(target);});
    return job.promise;
  }
  function loadingContent(){return '<div class="messages-loading" aria-hidden="true"><span></span><span></span><span></span></div>';}
  function updatePending(){
    const panel=$('#messages-pending');panel.hidden=!pendingPost||!person;
    $('#messages-pending-label').textContent=person?`Enviar este Ressoa para @${person.handle}`:'';
    $('#messages-send-post').disabled=sending;
  }
  function avatar(value){return `<span class="profile-avatar">${value.photo?`<img src="${escape(value.photo)}" alt="">`:escape(value.displayName.slice(0,2).toUpperCase())}</span>`;}
  function renderHeader(value=null){
    dialog.dataset.view=value?'chat':'inbox';
    $('#messages-title').textContent=value?value.displayName||'Conversa':pendingPost?'Enviar Ressoa':'Mensagens';
    $('#messages-subtitle').hidden=!value;
    $('#messages-subtitle').textContent=value?.handle?'@'+value.handle:value?'Carregando…':'';
    const photo=$('#messages-avatar');photo.hidden=!value?.displayName;photo.innerHTML=value?.displayName?avatar(value):'';
  }
  function resizeInput(){input.style.height='auto';input.style.height=Math.min(input.scrollHeight,128)+'px';}
  function ownReaction(reactions,emoji){
    const result=(reactions||[]).map(item=>({...item,count:item.count-(item.mine?1:0),mine:false})).filter(item=>item.count>0);
    if(emoji){let item=result.find(item=>item.emoji===emoji);if(!item){item={emoji,count:0,mine:false};result.push(item);}item.count++;item.mine=true;}
    return result.sort((a,b)=>a.emoji.localeCompare(b.emoji));
  }
  function renderReactions(node,message){
    const canReact=message.senderId!==self();
    const job=reactionJobs.get(message.id),reactions=job?ownReaction(message.reactions,job.emoji):(message.reactions||[]);
    const holder=node.querySelector('.message-reactions'),signature=JSON.stringify([reactions,!!job,canReact]);
    if(holder.dataset.signature!==signature){
      holder.dataset.signature=signature;
      holder.innerHTML=reactions.map(item=>{const label=reactionEmojis.find(([emoji])=>emoji===item.emoji)?.[1]||'Emoji';return canReact?`<button type="button" class="message-reaction${item.mine?' mine':''}" data-react-emoji="${escape(item.emoji)}" aria-pressed="${item.mine}" aria-label="${escape((item.mine?'Remover minha reação: ':'Reagir com ')+label)}" title="${escape(label)} · ${item.mine?'Você':'@'+(person?.handle||'')}" ${job?'disabled':''}><span aria-hidden="true">${escape(item.emoji)}</span></button>`:`<span class="message-reaction" role="img" aria-label="${escape('@'+(person?.handle||'')+' reagiu com '+label)}" title="${escape('@'+(person?.handle||'')+' reagiu com '+label)}"><span aria-hidden="true">${escape(item.emoji)}</span></span>`;}).join('');
    }
    node.classList.toggle('has-reactions',reactions.length>0);
    const control=node.querySelector('[data-message-react]');if(control){control.disabled=!!job;control.setAttribute('aria-busy',String(!!job));}
  }
  function renderReactionPicker(){
    const message=items.find(item=>item.id===reactionTarget),mine=message?.reactions?.find(item=>item.mine)?.emoji;
    const emojiButton=([emoji,label])=>`<button type="button" data-pick-reaction="${escape(emoji)}" aria-label="${escape(label)}" aria-pressed="${mine===emoji}" title="${escape(label)}"><span aria-hidden="true">${emoji}</span></button>`;
    reactionQuick.innerHTML=reactionEmojis.slice(0,5).map(emojiButton).join('')+'<button type="button" id="message-reaction-expand" aria-label="Mais emojis" aria-expanded="false" aria-controls="message-reaction-more"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg></button>';
    reactionMore.innerHTML=reactionEmojis.slice(5).map(emojiButton).join('');reactionMore.hidden=true;
  }
  async function reactToMessage(identifier,emoji){
    const message=items.find(item=>item.id===identifier);if(!message||message.senderId===self()||reactionJobs.has(identifier))return;
    const desired=message.reactions?.some(item=>item.mine&&item.emoji===emoji)?null:emoji;
    const job={emoji:desired,account:owner,epoch:cacheEpoch};reactionJobs.set(identifier,job);
    const render=()=>{const node=[...thread.children].find(node=>node.dataset.message===identifier);const item=items.find(item=>item.id===identifier);if(node&&item)renderReactions(node,item);};
    render();
    try{
      const data=await api('/api/messages/reaction',{method:'PUT',body:{messageId:identifier,emoji:desired}});
      if(job.account!==self()||job.epoch!==cacheEpoch)return;
      reactionChanges.set(identifier,{version:data.summary.version,reactions:data.reactions});
      if(reactionChanges.size>100)reactionChanges.delete(reactionChanges.keys().next().value);
      for(const item of items)if(item.id===identifier)item.reactions=data.reactions;
      for(const cached of conversationCache.values())for(const item of cached.items)if(item.id===identifier)item.reactions=data.reactions;
      updateSummary(data.summary);
    }catch(error){if(job.account===self()&&job.epoch===cacheEpoch)toast(error.message);}
    finally{if(reactionJobs.get(identifier)===job){reactionJobs.delete(identifier);render();}}
  }
  reactionDialog.addEventListener('click',event=>{
    const expand=event.target.closest('#message-reaction-expand');
    if(expand){reactionMore.hidden=!reactionMore.hidden;expand.setAttribute('aria-expanded',String(!reactionMore.hidden));if(!reactionMore.hidden)reactionMore.querySelector('button')?.focus();return;}
    const choice=event.target.closest('[data-pick-reaction]');if(choice){const identifier=reactionTarget;reactionDialog.close();void reactToMessage(identifier,choice.dataset.pickReaction);}
  });
  reactionDialog.addEventListener('close',()=>{reactionTarget=null;});
  function renderInbox(){
    $('#messages-list-label').hidden=!conversations.length;
    list.innerHTML=conversations.length?conversations.map(item=>`<button type="button" class="message-conversation${item.unreadCount?' unread':''}" data-conversation="${escape(item.person.id)}" aria-label="${escape(item.person.displayName+(item.unreadCount?', '+item.unreadCount+' novidades não lidas':''))}">${avatar(item.person)}<span class="message-conversation-copy"><span class="message-conversation-name"><strong>${escape(item.person.displayName)}</strong><span>@${escape(item.person.handle)}</span></span><small>${escape(item.sentByMe?'Você: ':'')}${escape(item.preview)}</small></span><span class="message-conversation-meta"><time datetime="${escape(item.updatedAt)}" title="${escape(stamp(item.updatedAt))}">${escape(inboxTime(item.updatedAt))}</time>${item.unreadCount?`<span class="message-unread" aria-hidden="true">${unreadLabel(item.unreadCount)}</span>`:''}</span></button>`).join(''):`<div class="empty message-empty">${emptyIcon}<h3>Nenhuma conversa ainda</h3><p>Busque alguém para enviar uma mensagem ou um Ressoa.</p></div>`;
    more.hidden=!inboxCursor;
  }
  function ressoaMarkup(message){
    if(message.loading)return '<p class="form-note">Atualizando Ressoa…</p>';
    const post=message.post;if(message.unavailable||!post)return '<p class="form-note">Este Ressoa não está mais disponível para você.</p>';
    const track=post.track,index=registerTrack(track);message.trackIndex=index;
    const attribution=track.provider==='spotify'?`<a class="spotify-attribution" href="${escape(track.url)}" target="_blank" rel="noopener noreferrer" aria-label="Ouvir no Spotify"><img src="assets/spotify-white.svg" alt="Spotify" width="60" height="18"></a>`:'';
    return `<div class="message-ressoa"><div class="message-ressoa-cover"><button type="button" class="cover-open" data-music="${index}" aria-label="Sobre ${escape(track.title)}">${albumArt({artwork:track.artwork||'assets/cover-unavailable.svg',album:track.album||track.title,excerpt:post.lyricExcerpt,size:220})}</button><button type="button" class="cover-play" data-dm-play="${escape(message.id)}" aria-label="Ouvir trecho" aria-pressed="false"><span aria-hidden="true">▶</span></button></div><div class="message-ressoa-details"><p class="message-ressoa-label">${message.kind==='post'?'Ressoa compartilhado':'Só nesta conversa'}</p><h3><button type="button" class="track-name" data-music="${index}">${escape(track.title)}</button></h3><p class="artist">${escape(track.artist)}</p>${attribution}</div>${post.text?`<p class="message-ressoa-text">${escape(post.text)}</p>`:''}${message.kind==='post'?`<button type="button" class="text-button message-open" data-dm-open-post="${escape(post.id)}">Abrir Ressoa <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg></button>`:''}</div>`;
  }
  function renderMessages(forceBottom=false,prepend=false){
    const atBottom=thread.scrollHeight-thread.clientHeight-thread.scrollTop<80,oldHeight=thread.scrollHeight,oldTop=thread.scrollTop;
    observer.disconnect();visible.clear();
    const nodes=new Map([...thread.children].map(node=>[node.dataset.message,node]));
    if(!items.length){thread.innerHTML=`<div class="empty message-empty">${emptyIcon}<h3>Ainda não há mensagens</h3><p>Escreva abaixo ou use o + para enviar um Ressoa.</p></div>`;return;}
    thread.querySelector('.empty')?.remove();
    let position=0;
    for(const message of items){
      let node=nodes.get(message.id);const signature=JSON.stringify([message.kind,message.text,message.post,message.unavailable,message.loading]);
      if(!node){node=document.createElement('article');node.dataset.message=message.id;}
      node.className='message-bubble'+(message.senderId===self()?' sent':' received')+(message.kind!=='text'?' has-ressoa':'');
      if(node.dataset.signature!==signature){
        if(node.querySelector('.cover-play.playing'))stopPreview();
        node.dataset.signature=signature;
        node.innerHTML=(message.kind==='text'?`<p class="message-text">${escape(message.text)}</p>`:ressoaMarkup(message))+`<div class="message-footer">${message.senderId!==self()?`<button type="button" class="message-react" data-message-react="${escape(message.id)}" aria-label="Reagir à mensagem" aria-haspopup="dialog" aria-controls="message-reaction-dialog" title="Reagir">${smileIcon}</button>`:''}<time datetime="${escape(message.createdAt)}" title="${escape(stamp(message.createdAt))}" aria-label="${escape(stamp(message.createdAt))}">${escape(clock(message.createdAt))}</time></div><span class="message-reactions" role="group" aria-label="Reações à mensagem"></span>`;
      }
      renderReactions(node,message);
      if(thread.children[position]!==node)thread.insertBefore(node,thread.children[position]||null);
      position++;observer.observe(node);nodes.delete(message.id);
    }
    for(const node of nodes.values())node.remove();
    fitLyricArt(thread);
    if(prepend)thread.scrollTop=oldTop+thread.scrollHeight-oldHeight;
    else if(forceBottom||atBottom)thread.scrollTop=thread.scrollHeight;
    older.hidden=!cursor;
  }
  async function loadInbox(append=false){
    resetRequest();request=new AbortController();const token=generation,account=owner;
    if(!inboxLoaded||append)status.textContent='Carregando…';more.disabled=true;
    list.setAttribute('aria-busy',String(!inboxLoaded));
    try{
      const data=append?await api('/api/messages?'+new URLSearchParams({cursor:inboxCursor}),{signal:request.signal}):await fetchInbox();
      if(token!==generation||account!==self()||person||!dialog.open)return;
      if(append){const known=new Map(conversations.map(item=>[item.person.id,item]));data.items.forEach(item=>known.set(item.person.id,item));conversations=[...known.values()];inboxCursor=data.nextCursor;}
      loadedVersion=inboxVersion;updateSummary(data.summary);renderInbox();status.textContent='';
    }catch(error){if(error.name!=='AbortError'&&token===generation)status.textContent=error.message;}
    finally{if(token===generation){request=null;more.disabled=false;list.setAttribute('aria-busy','false');}}
  }
  async function loadConversation(append=false,initial=false){
    if(!person)return;resetRequest();request=new AbortController();const token=generation,target=person.id,account=owner,existing=new Set(items.map(item=>item.id));
    if((initial&&!items.length)||append)status.textContent='Carregando…';older.disabled=true;thread.setAttribute('aria-busy',String(initial&&!items.length));
    try{
      const data=append?await api('/api/messages?'+new URLSearchParams({user:target,cursor}),{signal:request.signal}):await fetchConversation(target);
      if(token!==generation||account!==self()||person?.id!==target||!dialog.open)return;
      person=data.person;
      renderHeader(person);
      for(const item of items)if(Object.hasOwn(data.reactions||{},item.id)){item.reactions=data.reactions[item.id];reconcileReactions(item,data.summary.version);}
      for(const item of items)if(Object.hasOwn(data.reactionNotices||{},item.id))item.reactionNotice=data.reactionNotices[item.id];
      data.items.forEach(item=>reconcileReactions(item,data.summary.version));
      const kept=initial?items.filter(item=>item.senderId===account&&!existing.has(item.id)):items;
      const known=new Map(kept.map(item=>[item.id,item]));data.items.forEach(item=>known.set(item.id,item));
      items=[...known.values()].sort((a,b)=>a.createdAt.localeCompare(b.createdAt)||a.id.localeCompare(b.id));
      if(append||initial||items.length<=50)cursor=data.nextCursor;
      if(!append)loadedVersion=data.summary.version;
      if(initial)pendingRead=data.unreadCount?{user:target,through:data.readCursor,reactionThrough:data.reactionReadCursor}:null;
      updateSummary(data.summary);renderMessages(initial,append);status.textContent='';updatePending();
    }catch(error){if(error.name!=='AbortError'&&token===generation)status.textContent=error.message;}
    finally{if(token===generation){request=null;older.disabled=false;thread.setAttribute('aria-busy','false');}}
  }
  function showInbox(){
    pendingRead=null;
    if(reactionDialog.open)reactionDialog.close();
    if(person)drafts.set(person.id,input.value);stopPreview();resetRequest();person=null;items=[];cursor=null;observer.disconnect();visible.clear();
    inbox.hidden=false;chat.hidden=true;back.hidden=true;loadedVersion=inboxVersion;renderHeader();
    if(inboxLoaded)renderInbox();else{list.innerHTML=loadingContent();more.hidden=true;}
    search.value='';results.hidden=true;searchRequest?.abort();void loadInbox();
  }
  async function start(target){
    if(target===self())return;
    pendingRead=null;
    if(reactionDialog.open)reactionDialog.close();
    if(person)drafts.set(person.id,input.value);stopPreview();resetRequest();searchRequest?.abort();
    const saved=conversationCache.get(target),cached=saved&&Date.now()-saved.savedAt<300000?saved:null;
    person=cached?.person||conversations.find(item=>item.person.id===target)?.person||{id:target,handle:'',displayName:'',photo:''};
    // Reauthorize shared links before showing their content again; direct messages stay in this conversation.
    items=cached?cached.items.map(item=>item.kind==='post'?{...item,post:null,loading:true}:item):[];
    cursor=cached?.nextCursor||null;loadedVersion=cached?.summary.version??-1;observer.disconnect();visible.clear();thread.replaceChildren();
    inbox.hidden=true;chat.hidden=false;back.hidden=false;older.hidden=true;renderHeader(person);
    input.value=drafts.get(target)||'';submission=null;
    if(!dialog.open)dialog.showModal();resizeInput();updatePending();
    if(cached)renderMessages(true);else thread.innerHTML=loadingContent();
    await loadConversation(false,true);
    if(person?.id===target){renderHeader(person);$('#message-compose').setAttribute('aria-label','Criar Ressoa para @'+person.handle);}
  }
  async function readVisible(){
    if(reading||!dialog.open||!person||document.hidden)return;
    const box=thread.getBoundingClientRect(),top=document.elementFromPoint(box.left+box.width/2,box.top+Math.min(40,box.height/2));
    if(!top||!dialog.contains(top))return;
    const target=person.id,account=owner,epoch=cacheEpoch,opening=pendingRead?.user===target?pendingRead:null;
    const ids=items.filter(item=>item.senderId!==account&&!item.readAt&&visible.has(item.id)).slice(0,50).map(item=>item.id);
    const reactionReceipts=items.filter(item=>item.reactionNotice&&visible.has(item.id)).slice(0,50).map(item=>({messageId:item.id,createdAt:item.reactionNotice}));
    if((!opening&&!ids.length&&!reactionReceipts.length)||!visible.size)return;reading=true;
    const known=items.map(item=>({id:item.id,notice:item.reactionNotice}));
    try{
      const data=await api('/api/messages/read',{method:'POST',body:{user:target,ids,reactionReceipts,...(opening?{through:opening.through,reactionThrough:opening.reactionThrough}:{})}});
      if(account!==self()||epoch!==cacheEpoch)return;updateSummary(data.summary);
      if(pendingRead===opening)pendingRead=null;
      const mark=item=>{const previous=known.find(value=>value.id===item.id);if(!previous)return;
        if(item.senderId!==account&&(opening?.through||ids.includes(item.id)))item.readAt=new Date().toISOString();
        if(item.reactionNotice===previous.notice&&(opening?.reactionThrough||reactionReceipts.some(value=>value.messageId===item.id&&value.createdAt===item.reactionNotice)))item.reactionNotice=null;};
      if(person?.id===target)items.forEach(mark);
      const cached=conversationCache.get(target);cached?.items.forEach(mark);if(cached)cached.unreadCount=data.unreadCount;
      const conversation=conversations.find(item=>item.person.id===target);if(conversation)conversation.unreadCount=data.unreadCount;
      readCounts.set(target,{version:data.summary.version,count:data.unreadCount});
      if(readCounts.size>100)readCounts.delete(readCounts.keys().next().value);
      inboxVersion=-1;
    }catch{}finally{reading=false;}
  }
  async function sendPayload(body,target=person?.id){
    if(!target)throw new Error('Escolha uma conversa.');const account=owner;
    const data=await api('/api/messages',{method:'POST',body:{...body,user:target}});
    if(account!==self())return data;
    updateSummary(data.summary);
    const cached=conversationCache.get(target);
    if(cached){if(!cached.items.some(item=>item.id===data.message.id))cached.items.push(data.message);cached.summary=data.summary;}
    const recipient=person?.id===target?person:cached?.person||conversations.find(item=>item.person.id===target)?.person;
    if(recipient?.handle){
      const previous=conversations.find(item=>item.person.id===target);
      conversations=[{person:recipient,updatedAt:data.message.createdAt,unreadCount:previous?.unreadCount||0,preview:data.message.kind==='text'?data.message.text.slice(0,120):'Enviou um Ressoa',sentByMe:true},...conversations.filter(item=>item.person.id!==target)];
    }
    inboxVersion=-1;
    if(person?.id===target&&dialog.open){
      if(!items.some(item=>item.id===data.message.id))items.push(data.message);
      renderMessages(true);
    }
    return data;
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();const message=input.value.trim();if(!person||!message||sending)return;
    const target=person.id;sending=true;send.disabled=true;
    if(submission?.text!==message||submission?.user!==target)submission={id:newId(),kind:'text',text:message,user:target};
    try{await sendPayload(submission,target);drafts.delete(target);if(person?.id===target)input.value='';submission=null;status.textContent='';}
    catch(error){status.textContent=error.message;}
    finally{sending=false;send.disabled=false;resizeInput();updatePending();}
  });
  input.addEventListener('input',()=>{if(person)drafts.set(person.id,input.value);resizeInput();});
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!matchMedia('(pointer:coarse)').matches){event.preventDefault();form.requestSubmit();}});
  $('#message-compose').addEventListener('click',()=>{if(person)onCompose({...person});});
  $('#messages-send-post').addEventListener('click',async()=>{
    if(!pendingPost||!person||sending)return;sending=true;updatePending();
    try{await sendPayload({id:pendingShareId,kind:'post',postId:pendingPost});pendingPost=null;pendingShareId=null;status.textContent='';}
    catch(error){status.textContent=error.message;}
    finally{sending=false;updatePending();}
  });
  $('#messages-cancel-post').addEventListener('click',()=>{pendingPost=null;pendingShareId=null;updatePending();});
  thread.addEventListener('click',event=>{
    const reaction=event.target.closest('[data-message-react],[data-react-emoji]');
    if(reaction){const identifier=reaction.closest('[data-message]').dataset.message;
      if(reaction.hasAttribute('data-react-emoji'))void reactToMessage(identifier,reaction.dataset.reactEmoji);
      else{if(items.find(item=>item.id===identifier)?.senderId===self())return;reactionTarget=identifier;renderReactionPicker();reactionDialog.showModal();}return;}
    const play=event.target.closest('[data-dm-play]');if(play){const message=items.find(item=>item.id===play.dataset.dmPlay);if(message?.post)onPlay(play,message.trackIndex??registerTrack(message.post.track),event,message.post.audioExcerpt);return;}
    const open=event.target.closest('[data-dm-open-post]');if(open){dialog.close();onOpenPost(open.dataset.dmOpenPost);}
  });
  search.addEventListener('input',()=>{
    clearTimeout(searchTimer);searchRequest?.abort();results.replaceChildren();const q=search.value.trim();results.hidden=!q;if(!q)return;
    searchTimer=setTimeout(async()=>{
      searchRequest=new AbortController();const account=owner;
      try{
        const data=await api('/api/people?'+new URLSearchParams({q}),{signal:searchRequest.signal});
        if(account!==self()||search.value.trim()!==q||person||!dialog.open)return;
        results.innerHTML=data.people.filter(item=>item.id!==self()).map(item=>`<button type="button" class="message-person" data-new-conversation="${escape(item.id)}">${avatar(item)}<span>${escape(item.displayName)}<small>@${escape(item.handle)}</small></span></button>`).join('')||'<p class="form-note">Nenhuma pessoa encontrada.</p>';
      }catch(error){if(error.name!=='AbortError')results.textContent=error.message;}
    },200);
  });
  results.addEventListener('click',event=>{const item=event.target.closest('[data-new-conversation]');if(item)void start(item.dataset.newConversation);});
  list.addEventListener('click',event=>{const item=event.target.closest('[data-conversation]');if(item)void start(item.dataset.conversation);});
  button.addEventListener('click',()=>{pendingPost=null;pendingShareId=null;if(!dialog.open)dialog.showModal();showInbox();});
  back.addEventListener('click',showInbox);more.addEventListener('click',()=>void loadInbox(true));older.addEventListener('click',()=>void loadConversation(true));
  dialog.addEventListener('close',()=>{pendingRead=null;if(reactionDialog.open)reactionDialog.close();stopPreview();resetRequest();searchRequest?.abort();clearTimeout(searchTimer);clearTimeout(readTimer);observer.disconnect();visible.clear();if(person)drafts.set(person.id,input.value);});
  async function poll(force=false){
    if(document.hidden||polling||request||(!force&&!dialog.open&&Date.now()-lastPoll<8000))return;
    polling=true;lastPoll=Date.now();const account=owner;
    try{
      if(force&&dialog.open){if(person)await loadConversation();else await loadInbox();return;}
      if(!inboxLoaded&&!dialog.open){await fetchInbox();return;}
      const data=await api('/api/messages/summary');if(account!==self())return;updateSummary(data.summary);
      if(dialog.open&&(loadedVersion!==summary.version||force)){if(person)await loadConversation();else await loadInbox();}
      else if(!dialog.open&&inboxVersion!==summary.version)await fetchInbox();
    }catch{}finally{polling=false;}
  }
  window.addEventListener('accountchange',()=>{
    if(owner!==self()){owner=self();clearMemory();}
  });
  function clearMemory(){
    cacheEpoch++;
    inboxJob?.controller.abort();inboxJob=null;if(dialog.open)dialog.close();resetRequest();
    conversationJobs.forEach(job=>job.controller.abort());conversationJobs.clear();
    person=null;items=[];conversations=[];conversationCache.clear();drafts.clear();thread.replaceChildren();list.replaceChildren();
    reactionJobs.clear();reactionChanges.clear();
    readCounts.clear();
    pendingRead=null;
    inboxLoaded=false;inboxVersion=-1;loadedVersion=-1;pendingPost=null;submission=null;summary={version:-1,unreadCount:0};updateSummary(summary);
  }
  window.addEventListener('sessionexpired',clearMemory);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){void poll(true);void readVisible();}});
  document.addEventListener('close',()=>{if(dialog.open)setTimeout(readVisible,0);},true);
  setInterval(poll,4000);void poll(true);
  return {open(target){pendingPost=null;pendingShareId=null;return start(target);},share(postId){pendingPost=postId;pendingShareId=newId();if(!dialog.open)dialog.showModal();showInbox();},sendRessoa(post,target,id){return sendPayload({id,kind:'ressoa',post},target);}};
}

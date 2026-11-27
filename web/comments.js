import { api, getAccount } from './session.js';
import { newId } from './id.js';
const heart='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/></svg>';
const trash='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6m4-6v6"/></svg>';
export function createComments({ identity, toast, stopPreview, onConfirm }) {
  const $=id=>document.getElementById(id),dialog=$('comments-dialog'),list=$('comments-list'),status=$('comments-status'),more=$('comments-more');
  const form=$('comment-form'),input=form.elements.comment,retry=$('comments-retry'),replyPanel=$('comment-reply-context'),replyLabel=$('comment-reply-label');
  let postId=null,items=[],cursor=null,request=null,generation=0,sending=false,submission=null,replying=null;
  const drafts=new Map(),deleting=new Set(),liking=new Set(),threads=new Map();
  const allItems=()=>[...items,...[...threads.values()].flatMap(thread=>thread.items)];
  function cancelReply(){replying=null;submission=null;replyPanel.hidden=true;input.placeholder='O que essa música te faz pensar?';}
  function renderRow(item,reply=false){
    const row=document.createElement('article');row.className='comment-row'+(reply?' comment-reply':'');row.dataset.commentId=item.id;row.innerHTML=identity(item.person);
    const time=document.createElement('time');time.dateTime=item.createdAt;time.textContent=new Date(item.createdAt).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
    const text=document.createElement('p');text.className='comment-text';
    if(item.replyHandle){const name=document.createElement('span');name.className='comment-reply-to';name.textContent='@'+item.replyHandle+' ';text.append(name);}
    text.append(document.createTextNode(item.text));
    const actions=document.createElement('div');actions.className='comment-actions';
    const like=document.createElement('button');like.type='button';like.className='comment-like';like.dataset.likeComment=item.id;like.setAttribute('aria-pressed',String(item.liked));like.setAttribute('aria-label',item.liked?'Descurtir comentário':'Curtir comentário');like.disabled=liking.has(item.id);like.innerHTML=heart;
    const count=document.createElement('span');count.textContent=String(item.likeCount||0);like.append(count);
    const answer=document.createElement('button');answer.type='button';answer.className='text-button';answer.dataset.replyComment=item.id;answer.textContent='Responder';actions.append(like,answer);
    row.append(time,text,actions);
    if(item.canDelete){const remove=document.createElement('button');remove.type='button';remove.className='icon-button comment-delete';remove.dataset.deleteComment=item.id;remove.innerHTML=trash;remove.setAttribute('aria-label','Apagar comentário');remove.title='Apagar comentário';remove.disabled=deleting.has(item.id);row.append(remove);}
    return row;
  }
  function render(){
    const top=list.scrollTop;items.sort((a,b)=>a.createdAt.localeCompare(b.createdAt)||a.id.localeCompare(b.id));list.replaceChildren();
    if(!items.length){const empty=document.createElement('p');empty.className='empty';empty.textContent='Nenhum comentário ainda.';list.append(empty);}
    for(const item of items){
      const group=document.createElement('section');group.className='comment-group';group.append(renderRow(item));const thread=threads.get(item.id);
      if(item.replyCount||thread?.items.length){
        const toggle=document.createElement('button');toggle.type='button';toggle.className='text-button comment-replies-toggle';toggle.dataset.commentReplies=item.id;toggle.setAttribute('aria-expanded',String(!!thread?.open));toggle.textContent=thread?.loading?'Carregando respostas…':thread?.open?'Ocultar respostas':'Ver respostas ('+(item.replyCount||thread?.items.length||0)+')';toggle.disabled=!!thread?.loading;group.append(toggle);
      }
      if(thread?.open){
        const replies=document.createElement('div');replies.className='comment-replies';replies.setAttribute('aria-label','Respostas ao comentário');thread.items.forEach(reply=>replies.append(renderRow(reply,true)));group.append(replies);
        if(thread.cursor){const load=document.createElement('button');load.type='button';load.className='text-button comment-replies-toggle';load.dataset.moreReplies=item.id;load.textContent='Mais respostas';load.disabled=thread.loading;group.append(load);}
      }
      list.append(group);
    }
    more.hidden=!cursor;list.scrollTop=top;
  }
  async function load(append=false){
    request?.abort();request=new AbortController();const token=++generation,owner=getAccount().user.id;status.textContent='Carregando…';more.disabled=true;retry.hidden=true;
    try{
      const data=await api('/api/comments?'+new URLSearchParams({post:postId,...(append&&cursor?{cursor}:{})}),{signal:request.signal});
      if(token!==generation||!dialog.open||owner!==getAccount().user.id)return;
      const known=new Map((append?items:[]).map(item=>[item.id,item]));data.comments.forEach(item=>known.set(item.id,item));items=[...known.values()];cursor=data.nextCursor;render();status.textContent='';
    }catch(error){if(error.name!=='AbortError'&&token===generation){status.textContent=error.message;retry.hidden=false;retry.dataset.append=String(append);}}
    finally{if(token===generation){request=null;more.disabled=false;}}
  }
  async function loadReplies(root,append=false){
    const thread=threads.get(root)||{items:[],cursor:null,open:true};if(thread.loading)return;threads.set(root,thread);thread.open=true;thread.loading=true;render();const token=generation,target=postId;
    try{
      const data=await api('/api/comments?'+new URLSearchParams({post:target,parent:root,...(append&&thread.cursor?{cursor:thread.cursor}:{})}));
      if(token!==generation||postId!==target||!dialog.open)return;
      const known=new Map(thread.items.map(item=>[item.id,item]));data.comments.forEach(item=>known.set(item.id,item));thread.items=[...known.values()].sort((a,b)=>a.createdAt.localeCompare(b.createdAt)||a.id.localeCompare(b.id));thread.cursor=data.nextCursor;
    }catch(error){if(token===generation)toast(error.message);}
    finally{thread.loading=false;if(token===generation)render();}
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();const text=input.value.trim();if(sending||!text)return;
    sending=true;const target=postId,reply=replying,token=generation,button=form.querySelector('[type=submit]');button.disabled=true;button.textContent='Enviando…';input.readOnly=true;
    if(submission?.postId!==target||submission.text!==text||submission.replyToId!==(reply?.id||undefined))submission={id:newId(),postId:target,text,...(reply?{replyToId:reply.id}:{})};
    try{
      const result=await api('/api/comments',{method:'POST',body:submission});submission=null;drafts.delete(target);if(postId!==target||token!==generation||!dialog.open)return;
      input.value='';cancelReply();
      if(result.comment.parentId){
        const root=result.comment.parentId,thread=threads.get(root)||{items:[],open:true,cursor:null};threads.set(root,thread);thread.open=true;
        if(!thread.items.some(item=>item.id===result.comment.id)){thread.items.push(result.comment);const parent=items.find(item=>item.id===root);if(parent)parent.replyCount++;}
        render();void loadReplies(root);
      }else{if(!items.some(item=>item.id===result.comment.id))items.push(result.comment);render();}
      [...list.querySelectorAll('[data-comment-id]')].find(node=>node.dataset.commentId===result.comment.id)?.scrollIntoView({block:'nearest'});
    }catch(error){toast(error.message);}
    finally{sending=false;button.disabled=false;button.textContent='Enviar';input.readOnly=false;}
  });
  input.addEventListener('input',()=>{if(postId)drafts.set(postId,input.value);});$('comment-cancel-reply').addEventListener('click',cancelReply);
  list.addEventListener('click',async event=>{
    if(event.target.closest('[data-person]')){dialog.close();return;}
    const reply=event.target.closest('[data-reply-comment]');
    if(reply){replying=allItems().find(item=>item.id===reply.dataset.replyComment);if(!replying)return;replyLabel.textContent='Respondendo a @'+replying.person.handle;replyPanel.hidden=false;submission=null;input.placeholder='Escreva sua resposta…';input.focus();return;}
    const toggle=event.target.closest('[data-comment-replies],[data-more-replies]');
    if(toggle){const root=toggle.dataset.commentReplies||toggle.dataset.moreReplies,thread=threads.get(root);if(thread?.open&&!toggle.dataset.moreReplies){thread.open=false;render();}else void loadReplies(root,!!toggle.dataset.moreReplies);return;}
    const like=event.target.closest('[data-like-comment]');
    if(like){
      const item=allItems().find(item=>item.id===like.dataset.likeComment);if(!item||liking.has(item.id))return;
      const old={liked:item.liked,likeCount:item.likeCount},target=postId,token=generation;liking.add(item.id);item.liked=!item.liked;item.likeCount+=item.liked?1:-1;render();
      try{const result=await api('/api/comments/like',{method:'PUT',body:{id:item.id,postId:target,active:item.liked}});if(token===generation){item.liked=result.liked;item.likeCount=result.likeCount;}}
      catch(error){Object.assign(item,old);toast(error.message);}finally{liking.delete(item.id);if(token===generation)render();}return;
    }
    const remove=event.target.closest('[data-delete-comment]');if(!remove||deleting.has(remove.dataset.deleteComment))return;
    const item=allItems().find(item=>item.id===remove.dataset.deleteComment);if(!item)return;const target=postId,token=generation;
    onConfirm('Apagar comentário?',item.replyCount?'O comentário e suas respostas serão removidos.':'Esse comentário será removido do Ressoa.',async()=>{
      deleting.add(item.id);render();
      try{
        const result=await api('/api/comments',{method:'DELETE',body:{id:item.id,postId:target}});if(token!==generation)return;
        const ids=new Set(result.deletedIds);items=items.filter(item=>!ids.has(item.id));
        for(const [id,thread] of threads){if(ids.has(id))threads.delete(id);else thread.items=thread.items.filter(item=>!ids.has(item.id));}
        if(item.parentId){const root=items.find(root=>root.id===item.parentId);if(root)root.replyCount=Math.max(0,root.replyCount-1);}
        if(replying&&ids.has(replying.id))cancelReply();render();
      }catch(error){toast(error.message);}finally{deleting.delete(item.id);if(token===generation)render();}
    });
  });
  more.addEventListener('click',()=>void load(true));retry.addEventListener('click',()=>void load(retry.dataset.append==='true'));
  dialog.addEventListener('close',()=>{request?.abort();request=null;generation++;});
  window.addEventListener('privacychange',()=>{dialog.close();items=[];threads.clear();drafts.clear();cancelReply();list.replaceChildren();});
  return {open(id){if(sending&&postId!==id){toast('Aguarde o envio do comentário.');return;}stopPreview();postId=id;items=[];cursor=null;threads.clear();cancelReply();list.replaceChildren();more.hidden=true;input.value=drafts.get(id)||'';if(!dialog.open)dialog.showModal();void load();}};
}

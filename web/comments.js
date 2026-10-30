import { api } from './session.js';
import { newId } from './id.js';

export function createComments({ identity, toast, stopPreview }) {
  const dialog=document.getElementById('comments-dialog'),list=document.getElementById('comments-list');
  const status=document.getElementById('comments-status'),more=document.getElementById('comments-more');
  const form=document.getElementById('comment-form'),input=form.elements.comment;
  const retry=document.getElementById('comments-retry');
  let postId=null,items=[],cursor=null,request=null,generation=0,sending=false,submission=null;
  const drafts=new Map(),deleting=new Set();
  function render() {
    items.sort((a,b)=>a.createdAt.localeCompare(b.createdAt)||a.id.localeCompare(b.id));
    list.replaceChildren();
    if(!items.length){const empty=document.createElement('p');empty.className='empty';empty.textContent='Nenhum comentário ainda.';list.append(empty);}
    for(const item of items) {
      const row=document.createElement('article');row.className='comment-row';row.dataset.commentId=item.id;
      row.innerHTML=identity(item.person);
      const time=document.createElement('time');time.dateTime=item.createdAt;
      time.textContent=new Date(item.createdAt).toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
      const text=document.createElement('p');text.className='comment-text';text.textContent=item.text;
      row.append(time,text);
      if(item.canDelete){const remove=document.createElement('button');remove.type='button';remove.className='icon-button comment-delete';remove.dataset.deleteComment=item.id;remove.textContent='×';remove.setAttribute('aria-label','Apagar comentário');remove.disabled=deleting.has(item.id);row.append(remove);}
      list.append(row);
    }
    more.hidden=!cursor;
  }
  async function load(append=false) {
    request?.abort();request=new AbortController();const token=++generation;
    status.textContent='Carregando…';more.disabled=true;retry.hidden=true;
    const query=new URLSearchParams({post:postId,...(append&&cursor?{cursor}:{})});
    try {
      const data=await api('/api/comments?'+query,{signal:request.signal});
      if(token!==generation||!dialog.open)return;
      const existing=new Map(items.map(item=>[item.id,item]));
      data.comments.forEach(item=>existing.set(item.id,item));items=[...existing.values()];cursor=data.nextCursor;
      render();status.textContent='';
    } catch(error) {if(error.name!=='AbortError'&&token===generation){status.textContent=error.message;retry.hidden=false;retry.dataset.append=String(append);}}
    finally{if(token===generation){request=null;more.disabled=false;}}
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();const text=input.value.trim();if(sending||!text)return;
    sending=true;const id=postId,button=form.querySelector('[type="submit"]');button.disabled=true;button.textContent='Enviando…';input.readOnly=true;
    if(submission?.postId!==id||submission.text!==text)submission={id:newId(),postId:id,text};
    try {
      const result=await api('/api/comments',{method:'POST',body:submission});submission=null;
      drafts.delete(id);
      if(postId===id&&dialog.open){input.value='';if(!items.some(item=>item.id===result.comment.id))items.push(result.comment);render();list.lastElementChild?.scrollIntoView({block:'nearest'});}
    }catch(error){toast(error.message);}
    finally{sending=false;button.disabled=false;button.textContent='Enviar';input.readOnly=false;}
  });
  input.addEventListener('input',()=>{if(postId)drafts.set(postId,input.value);});
  list.addEventListener('click',async event=>{
    if(event.target.closest('[data-person]')){dialog.close();return;}
    const control=event.target.closest('[data-delete-comment]');if(!control||deleting.has(control.dataset.deleteComment))return;
    const id=control.dataset.deleteComment,target=postId;deleting.add(id);control.disabled=true;
    try{await api('/api/comments',{method:'DELETE',body:{id,postId:target}});if(postId===target){items=items.filter(item=>item.id!==id);render();}}
    catch(error){toast(error.message);}finally{deleting.delete(id);if(control.isConnected)control.disabled=false;}
  });
  more.addEventListener('click',()=>void load(true));
  retry.addEventListener('click',()=>void load(retry.dataset.append==='true'));
  dialog.addEventListener('close',()=>{request?.abort();request=null;generation++;});
  return {open(id){
    if(sending&&postId!==id){toast('Aguarde o envio do comentário.');return;}
    stopPreview();postId=id;items=[];cursor=null;list.replaceChildren();more.hidden=true;
    input.value=drafts.get(id)||'';if(!dialog.open)dialog.showModal();void load();
  }};
}

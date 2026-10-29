import { api, getAccount } from './session.js';
import { normalizeUsername } from './username.js';

export const personHref=id=>id==='me'||id===getAccount().user.id?'#perfil':`#pessoa/${encodeURIComponent(id)}`;

export function createPeopleSearch(root) {
  const input=root.querySelector('#people-query'),panel=root.querySelector('#people-search-panel');
  const list=root.querySelector('#people-results'),status=root.querySelector('#people-search-status'),clear=root.querySelector('#clear-people-search');
  const toggle=root.querySelector('#toggle-people-search');
  let timer,request,generation=0,active=-1;
  const query=()=>normalizeUsername(input.value);
  function close(collapse=false) {
    clearTimeout(timer);request?.abort();generation++;
    panel.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');input.removeAttribute('aria-busy');active=-1;
    if(collapse){root.dataset.open='false';toggle.setAttribute('aria-expanded','false');}
  }
  function open() {panel.hidden=false;input.setAttribute('aria-expanded','true');}
  function highlight(index) {
    if(!list.children.length)return;
    active=(index+list.children.length)%list.children.length;
    [...list.children].forEach((option,index)=>option.setAttribute('aria-selected',String(index===active)));
    input.setAttribute('aria-activedescendant',list.children[active].id);
    list.children[active].scrollIntoView({block:'nearest'});
  }
  async function search() {
    const term=query();if(!term)return;
    const token=++generation;request?.abort();request=new AbortController();
    input.setAttribute('aria-busy','true');list.replaceChildren();status.textContent='Buscando…';open();
    try {
      const data=await api(`/api/people?${new URLSearchParams({q:term})}`,{signal:request.signal});
      if(token!==generation)return;
      const fragment=document.createDocumentFragment();
      data.people.forEach((person,index)=>{
        const link=document.createElement('a');link.className='people-result';link.href=personHref(person.id);link.dataset.person=person.id;
        link.id=`person-result-${index}`;link.setAttribute('role','option');link.setAttribute('aria-selected','false');link.tabIndex=-1;
        const avatar=document.createElement('span');avatar.className='avatar';avatar.setAttribute('aria-hidden','true');
        if(person.photo){const image=document.createElement('img');image.src=person.photo;image.alt='';avatar.append(image);}else avatar.textContent=person.displayName.slice(0,2).toUpperCase();
        const copy=document.createElement('span'),name=document.createElement('strong'),handle=document.createElement('small');
        name.textContent=person.displayName;handle.textContent=`@${person.handle}${person.id===getAccount().user.id?' · você':''}`;
        copy.append(name,handle);link.append(avatar,copy);fragment.append(link);
      });
      list.replaceChildren(fragment);status.textContent=data.people.length?'':'Nenhuma pessoa encontrada.';
    } catch(error) {
      if(error.name==='AbortError'||token!==generation)return;
      status.textContent='Não foi possível buscar pessoas. ';
      const retry=document.createElement('button');retry.className='text-button';retry.textContent='Tentar novamente';retry.type='button';retry.onclick=()=>{input.focus();search();};status.append(retry);
    } finally {if(token===generation)input.removeAttribute('aria-busy');}
  }
  input.addEventListener('input',()=>{
    close();list.replaceChildren();status.textContent='';clear.hidden=!input.value;
    if(query())timer=setTimeout(search,250);
  });
  input.addEventListener('focus',()=>{if(query()&&(list.children.length||status.textContent))open();});
  input.addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);if(toggle.getClientRects().length)toggle.focus();}
    if(!panel.hidden&&list.children.length&&['ArrowDown','ArrowUp','Enter'].includes(event.key)){
      event.preventDefault();
      if(event.key==='Enter')list.children[active>=0?active:0].click();
      else highlight(active+(event.key==='ArrowDown'?1:-1));
    }
  });
  clear.addEventListener('click',()=>{input.focus();input.value='';clear.hidden=true;list.replaceChildren();status.textContent='';close();});
  toggle.addEventListener('click',()=>{
    if(root.dataset.open==='true'){close(true);return;}
    root.dataset.open='true';toggle.setAttribute('aria-expanded','true');input.focus();
  });
  list.addEventListener('click',event=>{if(event.target.closest('a'))close(true);});
  document.addEventListener('pointerdown',event=>{if(!root.contains(event.target))close(true);});
  root.addEventListener('focusout',event=>{if(!root.contains(event.relatedTarget))close(true);});
  return {close:()=>close(true)};
}

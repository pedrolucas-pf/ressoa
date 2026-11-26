import { api } from './session.js';
import { personHref } from './people-search.js';

const escape=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const literal=value=>value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');

export function mentionMarkup(value, mentions=[]) {
  const people=mentions.filter(item=>typeof item?.id==='string'&&typeof item?.handle==='string');
  if(!people.length)return escape(value);
  const names=[...new Set(people.map(item=>item.handle))].sort((a,b)=>b.length-a.length);
  const expression=new RegExp('(?<![\\p{L}\\p{N}_@])@('+names.map(literal).join('|')+')(?![\\p{L}\\p{N}_@.-])','gu');
  let result='',end=0;
  for(const match of value.matchAll(expression)){
    const person=people.find(item=>item.handle===match[1]);
    result+=escape(value.slice(end,match.index))+`<a class="mention-link" href="${escape(personHref(person.id))}" data-person="${escape(person.id)}">${escape(match[0])}</a>`;
    end=match.index+match[0].length;
  }
  return result+escape(value.slice(end));
}

export function createMentionPicker(input) {
  const panel=document.createElement('div');
  panel.className='mention-suggestions';panel.hidden=true;panel.setAttribute('role','listbox');
  panel.id=input.form.id+'-mentions';input.insertAdjacentElement('afterend',panel);
  const hint=document.createElement('small');hint.className='mention-hint';hint.textContent='Use @ para marcar. A pessoa só será avisada se puder ver o Ressoa.';panel.insertAdjacentElement('afterend',hint);
  input.setAttribute('aria-controls',panel.id);input.setAttribute('aria-autocomplete','list');
  let selected=[],people=[],request,timer,generation=0,active=0,enabled=true,choosing=false;
  function close(){clearTimeout(timer);request?.abort();request=null;generation++;panel.hidden=true;input.removeAttribute('aria-activedescendant');}
  function query(){
    if(!enabled||input.selectionStart!==input.selectionEnd)return null;
    const prefix=input.value.slice(0,input.selectionStart),start=prefix.lastIndexOf('@');
    if(start<0||(start&&/[\p{L}\p{N}_@]/u.test(prefix[start-1])))return null;
    if(selected.some(item=>prefix.slice(start).startsWith('@'+item.handle+' ')))return null;
    const value=prefix.slice(start+1);
    return value.length<=24&&!/[\r\n]/.test(value)?{start,end:input.selectionStart,value}:null;
  }
  function highlight(index){
    active=(index+people.length)%people.length;
    [...panel.children].forEach((item,i)=>item.setAttribute('aria-selected',String(i===active)));
    input.setAttribute('aria-activedescendant',panel.children[active].id);
  }
  function choose(index){
    const context=query(),person=people[index];if(!context||!person)return;
    selected=selected.filter(item=>item.id!==person.id);selected.push({id:person.id,handle:person.handle});
    choosing=true;input.setRangeText('@'+person.handle+' ',context.start,context.end,'end');
    input.dispatchEvent(new Event('input',{bubbles:true}));choosing=false;close();input.focus();
  }
  async function search(){
    const context=query();if(!context?.value.trim()){close();return;}
    request?.abort();request=new AbortController();const token=++generation;
    try{
      const data=await api('/api/people?'+new URLSearchParams({q:context.value.trim()}),{signal:request.signal});
      if(token!==generation||query()?.value!==context.value)return;
      people=data.people.slice(0,8);panel.replaceChildren();
      people.forEach((person,index)=>{
        const button=document.createElement('button');button.type='button';button.id=panel.id+'-'+index;
        button.setAttribute('role','option');button.innerHTML=`<strong>@${escape(person.handle)}</strong><span>${escape(person.displayName)}</span>`;
        button.addEventListener('pointerdown',event=>event.preventDefault());button.addEventListener('click',()=>choose(index));panel.append(button);
      });
      panel.hidden=!people.length;if(people.length)highlight(0);
    }catch(error){if(error.name!=='AbortError')close();}
  }
  function refresh(){if(choosing)return;close();if(query()?.value.trim())timer=setTimeout(search,180);}
  input.addEventListener('input',refresh);input.addEventListener('click',refresh);
  input.addEventListener('keydown',event=>{
    if(panel.hidden)return;
    if(['ArrowUp','ArrowDown','Enter','Escape'].includes(event.key)){event.preventDefault();event.stopPropagation();}
    if(event.key==='Escape')close();
    else if(event.key==='Enter')choose(active);
    else if(event.key==='ArrowDown')highlight(active+1);
    else if(event.key==='ArrowUp')highlight(active-1);
  });
  document.addEventListener('pointerdown',event=>{if(event.target!==input&&!panel.contains(event.target))close();});
  input.closest('dialog')?.addEventListener('close',close);
  return {get value(){return selected.filter(item=>input.value.includes('@'+item.handle));},set(items=[]){selected=Array.isArray(items)?items.map(item=>({...item})):[];close();},enable(value){enabled=value;hint.hidden=!value;close();},close};
}

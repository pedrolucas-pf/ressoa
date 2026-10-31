import { albumArt, fitLyricArt } from './post-art.js';
import { getSpotifyStatus } from './spotify.js';

export function createLyricPicker({dialog,api,tracks,musicDetails,onSelect}) {
  const field=dialog.querySelector('#lyric-selection'),list=dialog.querySelector('#lyric-lines');
  const preview=dialog.querySelector('#lyric-preview'),use=dialog.querySelector('#use-lyric');
  const status=dialog.querySelector('#lyric-status'),error=dialog.querySelector('#lyric-selection-error');
  const sync=dialog.querySelector('#lyric-sync-audio'),audioOptions=dialog.querySelector('#lyric-audio-options');
  const audioNote=dialog.querySelector('#lyric-audio-note'),useAudio=dialog.querySelector('#lyric-use-audio');
  let scope=null,index=null,request=null,generation=0,lines=[],selected=[],audio=null,canSync=false,saving=false;
  const time=n=>`${Math.floor(n/60)}:${String(Math.floor(n%60)).padStart(2,'0')}`;
  const overlaps=line=>audio&&line.start<audio.end&&(line.end??musicDetails[index].duration)>audio.start;
  const selectedText=ids=>ids.map(id=>lines[id].text).join('\n');
  function matchSelection(){
    const text=field.value.trim();if(!text)return [];
    if(selectedText(selected)===text)return selected;
    const words=text.split('\n').map(line=>line.trim());if(words.length>3)return [];
    let best=[],distance=Infinity;
    lines.forEach((line,first)=>{
      if(line.text!==words[0])return;
      const match=[first];
      for(const word of words.slice(1)){
        const next=lines.findIndex((row,id)=>id>match.at(-1)&&row.text===word);
        if(next<0)return;match.push(next);
      }
      const score=Math.abs((line.start??first)-(audio?.start||0));
      if(score<distance){best=match;distance=score;}
    });return best;
  }
  function suggestion(){
    const ids=[];
    lines.forEach((line,id)=>{if(ids.length<3&&overlaps(line)&&Array.from(selectedText([...ids,id])).length<=120)ids.push(id);});
    return ids;
  }
  function scrollToLine(id){
    const row=list.children[id];if(!row)return;
    list.scrollTop+=row.getBoundingClientRect().top-list.getBoundingClientRect().top-list.clientHeight/3;
  }
  function render(){
    const value=field.value.trim(),valid=Array.from(value).length<=120&&value.split('\n').length<=3;
    selected=matchSelection();use.disabled=saving||!value||!valid;dialog.querySelector('#lyric-count').textContent=`${Array.from(value).length}/120`;
    if(!valid)error.textContent='Use até 3 versos e 120 caracteres.';
    preview.innerHTML=albumArt({artwork:musicDetails[index].artwork,album:tracks[index].album||tracks[index].title,excerpt:value,size:190});
    requestAnimationFrame(()=>fitLyricArt(preview));
    list.querySelectorAll('.lyric-line').forEach((button,id)=>{
      button.setAttribute('aria-pressed',String(selected.includes(id)));button.classList.toggle('in-audio',Boolean(canSync&&overlaps(lines[id])));
    });
    audioOptions.hidden=!canSync;useAudio.hidden=!canSync||!suggestion().length;
    const fits=selected.length&&lines[selected.at(-1)].start-lines[selected[0]].start<30;
    sync.disabled=!fits;
    if(canSync){
      audioNote.hidden=false;
      audioNote.textContent=!selected.length?'Escolha os versos ou escreva livremente.':!fits?'Os versos estão distantes; o áudio será mantido como você escolheu.':!sync.checked?'O áudio será mantido como você escolheu.':audio&&selected.every(id=>overlaps(lines[id]))?`Versos do áudio ${time(audio.start)} — ${time(audio.end)} em destaque.`:'O áudio acompanhará o primeiro verso selecionado.';
    }
  }
  field.addEventListener('input',()=>{selected=[];error.textContent='';render();});
  sync.addEventListener('change',render);
  useAudio.addEventListener('click',()=>{selected=suggestion();field.value=selectedText(selected);error.textContent='';render();scrollToLine(selected[0]);});
  list.addEventListener('click',event=>{
    const button=event.target.closest('[data-line]');if(!button)return;
    const id=Number(button.dataset.line);let ids,text;
    if(!field.value.trim()||selectedText(selected)===field.value.trim()){
      ids=(selected.includes(id)?selected.filter(value=>value!==id):[...selected,id]).sort((a,b)=>a-b);text=selectedText(ids);
    }else{
      const previous=field.value.trim().split('\n'),line=lines[id].text;
      text=(previous.includes(line)?previous.filter(value=>value!==line):[...previous,line]).join('\n');ids=[];
    }
    if(text.split('\n').length>3||Array.from(text).length>120){error.textContent='Esse trecho ficou longo. Ajuste a parte que quer usar no campo abaixo.';field.focus();return;}
    error.textContent='';field.value=text;selected=ids;render();
  });
  use.addEventListener('click',async()=>{
    if(use.disabled)return;
    const token=generation,text=field.value.trim();let audioStart=null;
    if(canSync&&sync.checked&&!sync.disabled&&selected.length&&!(audio&&selected.every(id=>overlaps(lines[id]))))audioStart=lines[selected[0]].start;
    saving=true;use.disabled=true;
    try{await onSelect(scope,text,{track:index,audioStart});if(token===generation)dialog.close();}
    catch(cause){if(token===generation)error.textContent=cause.message||'Não foi possível usar o trecho. Tente novamente.';}
    finally{if(token===generation){saving=false;render();}}
  });
  dialog.addEventListener('close',()=>{request?.abort();generation++;lines=[];selected=[];list.replaceChildren();preview.replaceChildren();});
  async function open(options){
    request?.abort();const token=++generation;scope=options.scope;index=options.track;
    field.value=options.excerpt||'';error.textContent='';lines=[];selected=[];canSync=false;saving=false;
    audio=options.audio?.source==='spotify'?options.audio:null;audioOptions.hidden=true;audioNote.hidden=true;list.replaceChildren();status.textContent='Buscando letra…';
    dialog.querySelector('#lyric-track-name').textContent=`${tracks[index].title} · ${tracks[index].artist}`;
    dialog.showModal();render();request=new AbortController();
    try{
      const track=tracks[index],params=new URLSearchParams({title:track.title,artist:track.artist,album:track.album||'',duration:musicDetails[index].duration||'0'});
      const [data,connection]=await Promise.all([api(`/api/lyrics?${params}`,{signal:request.signal}),getSpotifyStatus().catch(()=>({connected:false}))]);if(token!==generation)return;
      if(data.status!=='found'||!data.text){status.textContent='Letra não encontrada. Você pode escrever o trecho abaixo.';return;}
      const timed=Array.isArray(data.lines)?data.lines.filter(line=>typeof line.text==='string'&&line.text.trim()&&Number.isFinite(line.start)&&line.start>=0).slice(0,600).map(line=>({text:line.text.trim(),start:line.start,end:Number.isFinite(line.end)&&line.end>line.start?line.end:null})).sort((a,b)=>a.start-b.start):[];
      lines=timed.length?timed:data.text.split(/\r?\n/).map(text=>({text:text.trim(),start:null,end:null})).filter(line=>line.text).slice(0,600);
      canSync=timed.length>0&&musicDetails[index].provider==='spotify'&&connection.connected;
      audioNote.hidden=canSync;
      if(!canSync){audioNote.hidden=false;audioNote.textContent=!timed.length?'Não há horários disponíveis para sincronizar esta letra. Escolha áudio e versos livremente.':musicDetails[index].provider==='deezer'?'Na prévia Deezer, áudio e letra são escolhidos separadamente.':'Conecte o Spotify para sincronizar com os horários da letra.';}
      status.textContent='Selecione até 3 versos ou escreva uma parte no campo abaixo. Fonte: LRCLIB.';
      const fragment=document.createDocumentFragment();
      lines.forEach((line,id)=>{
        const button=document.createElement('button');button.type='button';button.className='lyric-line';button.dataset.line=String(id);button.setAttribute('aria-pressed','false');
        const text=document.createElement('span');text.textContent=line.text;button.append(text);
        if(line.start!==null){button.classList.add('has-time');const stamp=document.createElement('time');stamp.textContent=time(line.start);button.append(stamp);}
        fragment.append(button);
      });
      list.replaceChildren(fragment);
      if(!field.value.trim()&&canSync&&audio){selected=suggestion();field.value=selectedText(selected);}
      render();const first=selected[0]??(canSync?lines.findIndex(overlaps):-1);requestAnimationFrame(()=>{if(token===generation)scrollToLine(first);});
    }catch(cause){if(cause.name!=='AbortError'&&token===generation)status.textContent='Não foi possível buscar a letra. Você pode escrever o trecho abaixo.';}
  }
  return {open};
}

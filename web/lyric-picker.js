import { albumArt, fitLyricArt } from './post-art.js';

export function createLyricPicker({dialog,api,tracks,musicDetails,onSelect}) {
  const field=dialog.querySelector('#lyric-selection'),list=dialog.querySelector('#lyric-lines');
  const preview=dialog.querySelector('#lyric-preview'),use=dialog.querySelector('#use-lyric');
  const status=dialog.querySelector('#lyric-status'),error=dialog.querySelector('#lyric-selection-error');
  let scope=null,index=null,request=null,generation=0;
  function render() {
    const value=field.value.trim(),valid=Array.from(value).length<=120&&value.split('\n').length<=3;
    use.disabled=!value||!valid;dialog.querySelector('#lyric-count').textContent=`${Array.from(value).length}/120`;
    if(!valid)error.textContent='Use até 3 versos e 120 caracteres.';
    preview.innerHTML=albumArt({artwork:musicDetails[index].artwork,album:tracks[index].album||tracks[index].title,excerpt:value,size:190});
    requestAnimationFrame(()=>fitLyricArt(preview));
    list.querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed',String(value.split('\n').includes(button.textContent))));
  }
  field.addEventListener('input',()=>{error.textContent='';render();});
  list.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button)return;
    const selected=field.value.trim()?field.value.trim().split('\n'):[],line=button.textContent;
    const next=selected.includes(line)?selected.filter(value=>value!==line):[...selected,line];
    if(next.length>3||Array.from(next.join('\n')).length>120){error.textContent='Esse trecho ficou longo. Ajuste a parte que quer usar no campo abaixo.';field.focus();return;}
    error.textContent='';field.value=next.join('\n');render();
  });
  use.addEventListener('click',()=>{if(!use.disabled){onSelect(scope,field.value.trim());dialog.close();}});
  dialog.addEventListener('close',()=>{request?.abort();generation++;list.replaceChildren();preview.replaceChildren();});
  async function open(options) {
    request?.abort();const token=++generation;scope=options.scope;index=options.track;
    field.value=options.excerpt||'';error.textContent='';list.replaceChildren();status.textContent='Buscando letra…';
    dialog.querySelector('#lyric-track-name').textContent=`${tracks[index].title} · ${tracks[index].artist}`;
    dialog.showModal();render();request=new AbortController();
    try {
      const track=tracks[index],params=new URLSearchParams({title:track.title,artist:track.artist,album:track.album||'',duration:musicDetails[index].duration||'0'});
      const data=await api(`/api/lyrics?${params}`,{signal:request.signal});if(token!==generation)return;
      if(data.status!=='found'||!data.text){status.textContent='Letra não encontrada. Você pode escrever o trecho abaixo.';return;}
      status.textContent='Selecione até 3 versos ou escreva uma parte no campo abaixo. Fonte: LRCLIB.';
      const fragment=document.createDocumentFragment();
      for(const line of data.text.split(/\r?\n/).map(value=>value.trim()).filter(Boolean).slice(0,600)) {
        const button=document.createElement('button');button.type='button';button.className='lyric-line';button.textContent=line;button.setAttribute('aria-pressed','false');fragment.append(button);
      }
      list.replaceChildren(fragment);render();
    }catch(cause){if(cause.name!=='AbortError'&&token===generation)status.textContent='Não foi possível buscar a letra. Você pode escrever o trecho abaixo.';}
  }
  return {open};
}

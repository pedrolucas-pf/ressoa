import { sanitizeTrack } from './catalog-store.js';

let callbackNumber=0,serverUnavailableUntil=0;
const unavailable=()=>new Error('O catálogo de músicas está indisponível no momento. Tente novamente em instantes.');

// Deezer's public JSONP endpoint also works when the server cannot reach its API.
function deezer(path,parameters={},signal){
  return new Promise((resolve,reject)=>{
    if(signal?.aborted){reject(new DOMException('Consulta cancelada.','AbortError'));return;}
    const callback=`ressoaDeezer${Date.now()}${++callbackNumber}`,script=document.createElement('script');
    const url=new URL(path,'https://api.deezer.com/');
    url.search=new URLSearchParams({...parameters,output:'jsonp',callback});
    let timer,finished=false;
    const finish=(error,data)=>{
      if(finished)return;finished=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);script.remove();
      // A removed script may still finish downloading after cancellation.
      window[callback]=()=>{};setTimeout(()=>{delete window[callback];},30000);
      error?reject(error):resolve(data);
    };
    const abort=()=>finish(new DOMException('Consulta cancelada.','AbortError'));
    window[callback]=data=>{
      if(!data||typeof data!=='object'||data.error){finish(unavailable());return;}
      finish(null,data);
    };
    timer=setTimeout(()=>finish(unavailable()),8000);signal?.addEventListener('abort',abort,{once:true});
    script.src=url.href;script.async=true;script.onerror=()=>finish(unavailable());document.head.append(script);
  });
}
function trackFromDeezer(item){
  const album=item?.album||{},id=item?.id,release=album.release_date||item?.release_date||'';
  if(!Number.isSafeInteger(id)||id<=0)return null;
  return sanitizeTrack({catalogId:`deezer:${id}`,provider:'deezer',title:item.title,artist:item.artist?.name,
    album:album.title,year:String(release).slice(0,4),duration:item.duration,
    artwork:album.cover_big||album.cover_medium,previewUrl:item.preview,releaseDate:release,trackReleaseDate:item.release_date,
    contributors:Array.isArray(item.contributors)?item.contributors.map(person=>person?.name):[],bpm:item.bpm,isrc:item.isrc,explicit:item.explicit_lyrics});
}
async function server(path,signal){
  const controller=new AbortController();
  let timedOut=false;
  const abort=()=>controller.abort();signal?.addEventListener('abort',abort,{once:true});
  if(signal?.aborted)controller.abort();
  const timer=setTimeout(()=>{timedOut=true;abort();},4500);
  try{
    const response=await fetch(path,{signal:controller.signal,credentials:'same-origin',cache:'no-store'});
    const data=await response.json().catch(()=>null);
    if(!response.ok){
      const error=Object.assign(new Error(data?.error||'Não foi possível consultar as músicas.'),{status:response.status,code:data?.code});
      if(response.status===401)window.dispatchEvent(new Event('sessionexpired'));
      throw error;
    }
    if(!data||typeof data!=='object')throw unavailable();return data;
  }catch(error){
    if(timedOut&&!signal?.aborted)throw Object.assign(new Error('A consulta de músicas demorou para responder. Tente novamente.'),{status:504});
    throw error;
  }finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}
async function query(path,signal,fallback){
  if(signal?.aborted)throw new DOMException('Consulta cancelada.','AbortError');
  if(fallback&&Date.now()<serverUnavailableUntil)return fallback();
  try{return await server(path,signal);}
  catch(error){
    if(signal?.aborted)throw new DOMException('Consulta cancelada.','AbortError');
    // Authentication, validation and rate limits must keep their normal behavior.
    if(!fallback||(error.status&&![500,502,503,504].includes(error.status)))throw error;
    serverUnavailableUntil=Date.now()+30000;
    return fallback();
  }
}
export async function searchCatalog(term,{provider='deezer',offset=0,signal}={}){
  const text=term.trim();
  if(text.length<2||text.length>180)throw new Error('Digite de 2 a 180 caracteres.');
  const direct=text.match(/^(?:https:\/\/(?:www\.)?deezer\.com\/(?:[a-z]{2}\/)?track\/|deezer:)([0-9]{1,16})(?:\?[^\s]*)?\/?$/);
  const fallback=provider==='deezer'&&(direct||!text.match(/^(?:https?:\/\/|spotify:)/i))?async()=>{
    if(direct){
      if(offset)return {results:[],provider:'deezer',nextOffset:null};
      const track=trackFromDeezer(await deezer(`track/${direct[1]}`,{},signal));
      if(!track)throw unavailable();
      return {results:[track],provider:'deezer',nextOffset:null};
    }
    const data=await deezer('search',{q:text,limit:20,index:offset},signal);
    if(!Array.isArray(data.data))throw unavailable();
    const results=data.data.map(trackFromDeezer).filter(Boolean);
    return {results,provider:'deezer',nextOffset:data.next&&offset<240?offset+20:null};
  }:null;
  return query(`/api/search?${new URLSearchParams({q:text,provider,offset})}`,signal,fallback);
}
export async function catalogTrack(id,{signal,refresh=false}={}){
  const match=id.match(/^deezer:([0-9]{1,16})$/);
  const fallback=match?async()=>{
    const track=trackFromDeezer(await deezer(`track/${match[1]}`,{},signal));
    if(!track||track.catalogId!==id)throw unavailable();return track;
  }:null;
  return query(`/api/track?${new URLSearchParams({id,...(refresh?{refresh:'1'}:{})})}`,signal,fallback);
}

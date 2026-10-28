import { tracks, musicDetails, registerTrack } from './catalog-store.js';

const requests=new Map();
export const durationLabel = seconds => seconds ? `${Math.floor(Math.round(seconds)/60)}:${String(Math.round(seconds)%60).padStart(2,'0')}` : '';
export function trackSummary(index) {
  return [tracks[index]?.album,tracks[index]?.year,durationLabel(tracks[index]?.duration||musicDetails[index]?.duration)].filter(Boolean).join(' · ');
}
export async function ensureTrackDetails(index) {
  const detail=musicDetails[index];
  if(detail?.provider!=='deezer')return detail;
  const key=detail.catalogId;
  let record=requests.get(key);
  if(!record||record.expires<Date.now()) {
    const promise=fetch(`/api/track?${new URLSearchParams({id:key})}`).then(async response=>{
      if(!response.ok)throw new Error('Não foi possível carregar os dados da faixa.');
      const track=await response.json();
      if(track.catalogId!==key)throw new Error('Faixa inválida.');
      return track;
    }).catch(error=>{requests.delete(key);throw error;});
    record={promise,expires:Date.now()+240000};requests.set(key,record);
  }
  registerTrack(await record.promise);
  window.dispatchEvent(new CustomEvent('trackmetadata',{detail:{index}}));
  return musicDetails[index];
}

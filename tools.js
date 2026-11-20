// Runs on supercoach.com.au with the maintainer's own login and downloads the three raw files sc_import reads.
const code = `(async()=>{try{
if(location.hostname!=='www.supercoach.com.au')return alert('Open SuperCoach BBL first, logged in, then click this bookmark.');
const base='/2026/api/bbl/classic/v1/';
let t=localStorage.getItem('VMLS:news:accessToken');try{const j=JSON.parse(t);t=typeof j=='string'?j:j&&(j.accessToken||j.access_token||j.token)}catch(e){}
const seen=performance.getEntriesByType('resource').map(e=>e.name).filter(n=>new URL(n).origin===location.origin&&/\\/api\\/bbl\\/classic\\/v1\\/players-cf\\?/.test(n)&&n.includes('player_stats')).pop();
const get=async u=>{const r=await fetch(u,{headers:t?{Authorization:'Bearer '+t}:{}});if(!r.ok)throw new Error(u.split('?')[0].split('/').pop()+' answered '+r.status+'. Reload the page and try again.');return r.json()};
const settings=await get(base+'settings?min=false');
const fixture=await get(base+'real_fixture');
const c=settings.competition||{};
const url=new URL(seen||base+'players-cf?embed=notes%2Codds%2Cplayer_stats%2Cpositions',location.href);
url.searchParams.set('round',Math.max(1,c.next_round||c.current_round||1));
const ok=x=>Array.isArray(x)&&x.length&&x[0].player_stats;
const top=x=>Math.max(...x.flatMap(p=>p.player_stats.map(s=>s.round)));
const players=await get(url.href);
if(!settings.game||!Array.isArray(fixture)||!ok(players))throw new Error('SuperCoach sent something unexpected, so nothing was saved.');
const round=Math.max(1,top(players));
const save=(name,x)=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(x)],{type:'application/json'}));a.download=name;document.body.appendChild(a);a.click();a.remove()};
save('settings.json',settings);save('fixture.json',fixture);save('players-round'+round+'.json',players);
if(!players.some(p=>p.player_stats.some(s=>s.owned!=null)))alert('Saved, but SuperCoach sent no ownership for round '+round+'.');
}catch(e){alert('Save failed: '+e.message)}})()`;
document.getElementById('scsave').href = 'javascript:' + encodeURIComponent(code.replace(/\n/g, ''));
document.getElementById('scsave').addEventListener('click', e => e.preventDefault());

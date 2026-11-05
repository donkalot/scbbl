(function () {
  'use strict';

  const L = window.Logic;
  const $app = document.getElementById('app');
  const SQUAD_KEY = 'scbbl-squad';
  const D = {};
  const seasonCache = {};
  let grid, leagueRounds, squadOf, seasons;

  // ---------- helpers ----------
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  const fix = (v, d = 1) => (v == null || !isFinite(v) ? '–' : v.toFixed(d));
  const team = t => `<span class="team t-${esc(t || 'TBC')}">${esc(t || 'TBC')}</span>`;
  const day = d => new Date(d + 'T00:00:00Z').toLocaleDateString('en-AU', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
  const shortDay = d => new Date(d + 'T00:00:00Z').toLocaleDateString('en-AU', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  const newsDay = d => (Date.now() - Date.parse(d)) / 864e5 > 120
    ? new Date(d + 'T00:00:00Z').toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
    : shortDay(d);
  const when = iso => new Date(iso).toLocaleString('en-AU', { timeZone: 'Australia/Sydney', weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
  const go = hash => { location.hash = hash; };

  async function json(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }
  function season(s) {
    return seasonCache[s] || (seasonCache[s] = json(`data/matches/${s.replace('/', '-')}.json`));
  }
  let elsewhereP;
  const elsewhere = () => elsewhereP || (elsewhereP = json('data/elsewhere.json'));
  const yearDay = d => new Date(d + 'T00:00:00Z').toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: '2-digit', timeZone: 'UTC' });
  const monthYear = d => new Date(d + 'T00:00:00Z').toLocaleDateString('en-AU', { month: 'short', year: 'numeric', timeZone: 'UTC' });

  function mySquad() {
    try { return JSON.parse(localStorage.getItem(SQUAD_KEY)) || []; } catch { return []; }
  }
  function toggleSquad(pid) {
    const s = mySquad();
    const i = s.indexOf(pid);
    if (i >= 0) s.splice(i, 1); else s.push(pid);
    localStorage.setItem(SQUAD_KEY, JSON.stringify(s));
    return i < 0;
  }
  function squadButton(pid) {
    const inSquad = mySquad().includes(pid);
    return `<button class="sq${inSquad ? ' in' : ''}" data-squad="${esc(pid)}" title="${inSquad ? 'Remove from' : 'Add to'} my squad">${inSquad ? '✓' : '+'}</button>`;
  }
  $app.addEventListener('click', e => {
    const b = e.target.closest('[data-squad]');
    if (!b) return;
    const added = toggleSquad(b.dataset.squad);
    b.classList.toggle('in', added);
    b.textContent = added ? '✓' : '+';
    b.title = `${added ? 'Remove from' : 'Add to'} my squad`;
    if (b.dataset.rerender) route();
  });

  const name = pid => (squadOf[pid] && squadOf[pid].n) || (D.players[pid] && D.players[pid].n) || pid;
  const proj = pid => L.projAvg(D.players[pid], seasons);
  function link(pid) {
    return `<a href="#/player/${encodeURIComponent(pid)}">${esc(name(pid))}</a>`;
  }
  function rounds16(pid) {
    const s = squadOf[pid];
    return L.playerRounds(s && s.team, pid, grid, D.availability);
  }
  function roundLabel(r) {
    return `R${r.round} <span class="muted">${shortDay(r.start)}–${shortDay(r.end)}</span>`;
  }
  function draftBanner() {
    return D.rounds.draft ? `<div class="banner"><b>Draft rounds.</b> ${esc(D.rounds.note)}</div>` : '';
  }

  // ---------- players ----------
  function viewPlayers(params) {
    const st = { q: params.get('q') || '', team: params.get('team') || '', scope: params.get('scope') || 'squad', sort: params.get('sort') || 'proj' };
    $app.innerHTML = `
      <h2>Players</h2>
      <div class="row card">
        <input type="search" id="q" placeholder="Search players" value="${esc(st.q)}" aria-label="Search players">
        <select id="team" aria-label="Team"><option value="">All teams</option>${L.TEAMS.map(t => `<option${t === st.team ? ' selected' : ''}>${t}</option>`).join('')}</select>
        <select id="scope" aria-label="Which players">
          <option value="squad"${st.scope === 'squad' ? ' selected' : ''}>BBL|16 squads</option>
          <option value="mine"${st.scope === 'mine' ? ' selected' : ''}>My squad</option>
          <option value="all"${st.scope === 'all' ? ' selected' : ''}>Everyone since 2011</option>
        </select>
      </div>
      <p class="muted">Proj = average SC points over the last two seasons (career if fewer than 3 games). T20 elsewhere = SC points per game in T20Is and franchise T20 leagues over the last 12 months, scored with the same table (games in brackets; under 5 games sorts last). Squads as of ${esc(D.squads.as_of)}.</p>
      <div class="scroll"><table id="ptable"></table></div>`;
    const latest = seasons[seasons.length - 1];
    const ids = new Set(Object.keys(squadOf));
    for (const pid of Object.keys(D.players)) ids.add(pid);
    const rows = [...ids].map(pid => {
      const p = D.players[pid];
      const a = p && p.s[latest];
      const lastSeason = p ? Object.keys(p.s).sort().pop() : null;
      return { pid, n: name(pid), sq: squadOf[pid], last: a ? L.seasonLine(a) : null, a, proj: proj(pid),
               lastTeam: lastSeason && p.s[lastSeason].t, lastSeason };
    });
    // Fewer than 5 games is too small a sample to rank with everyone else.
    const elseRank = r => (!r.ew ? -2 : r.ew.m < 5 ? -1 + r.ew.avg / 1e4 : r.ew.avg);
    const sorters = {
      proj: (a, b) => (b.proj ?? -1) - (a.proj ?? -1),
      else: (a, b) => elseRank(b) - elseRank(a),
      name: (a, b) => a.n.localeCompare(b.n),
      runs: (a, b) => ((b.a && b.a.r) || 0) - ((a.a && a.a.r) || 0),
      wk: (a, b) => ((b.a && b.a.wk) || 0) - ((a.a && a.a.wk) || 0),
    };

    function render() {
      const q = st.q.trim().toLowerCase();
      const mine = new Set(mySquad());
      let list = rows.filter(r =>
        (st.scope === 'all' || (st.scope === 'mine' ? mine.has(r.pid) : r.sq)) &&
        (!st.team || (r.sq ? r.sq.team : r.lastTeam) === st.team) &&
        (!q || r.n.toLowerCase().includes(q)));
      list.sort(sorters[st.sort] || sorters.proj);
      const shown = list.slice(0, 200);
      const th = (key, label) => `<th${key === 'name' ? ' class="l"' : ''}><a href="#" data-sort="${key}">${label}${st.sort === key ? ' ▾' : ''}</a></th>`;
      document.getElementById('ptable').innerHTML = `
        <thead><tr><th></th>${th('name', 'Player')}<th class="l">Team</th>${th('proj', 'Proj')}${th('else', 'T20 elsewhere')}<th>M ${esc(latest)}</th><th>SC avg</th>${th('runs', 'Runs')}<th>SR</th>${th('wk', 'Wkts')}<th>Econ</th></tr></thead>
        <tbody>${shown.map(r => `<tr>
          <td>${squadButton(r.pid)}</td>
          <td class="l name">${link(r.pid)} ${r.sq && r.sq.os ? `<span class="pill os">${esc(r.sq.os)}</span>` : ''}${r.sq && r.sq.new ? ' <span class="pill">new</span>' : ''}</td>
          <td class="l">${r.sq ? team(r.sq.team) : `<span class="muted">${esc(r.lastTeam || '')} ${esc(r.lastSeason || '')}</span>`}</td>
          <td><b>${fix(r.proj)}</b></td>
          <td>${r.ew ? `${fix(r.ew.avg)} <span class="muted">(${r.ew.m})</span>` : ''}</td>
          <td>${r.a ? r.a.m : ''}</td><td>${r.last ? fix(r.last.avg) : ''}</td>
          <td>${r.a ? r.a.r : ''}</td><td>${r.last ? fix(r.last.sr, 0) : ''}</td>
          <td>${r.a ? r.a.wk : ''}</td><td>${r.last && r.a.lb ? fix(r.last.econ, 2) : ''}</td></tr>`).join('')}
        </tbody>`;
      if (list.length > shown.length) document.getElementById('ptable').insertAdjacentHTML('beforeend', `<caption class="muted" style="caption-side:bottom;padding:8px">Showing 200 of ${list.length}. Search to narrow.</caption>`);
      const qs = new URLSearchParams(Object.entries(st).filter(([k, v]) => v && !(k === 'scope' && v === 'squad') && !(k === 'sort' && v === 'proj')));
      history.replaceState(null, '', `#/players${qs.toString() ? '?' + qs : ''}`);
    }
    document.getElementById('q').addEventListener('input', e => { st.q = e.target.value; render(); });
    document.getElementById('team').addEventListener('change', e => { st.team = e.target.value; render(); });
    document.getElementById('scope').addEventListener('change', e => { st.scope = e.target.value; render(); });
    document.getElementById('ptable').addEventListener('click', e => {
      const a = e.target.closest('[data-sort]');
      if (!a) return;
      e.preventDefault();
      st.sort = a.dataset.sort;
      render();
    });
    render();
    elsewhere().then(e => {
      for (const r of rows) {
        const y = e.players[r.pid] && e.players[r.pid].y.t20;
        if (y && y.scm) r.ew = { avg: y.sc / y.scm, m: y.scm };
      }
      if (document.getElementById('ptable')) render();
    });
  }

  // ---------- player ----------
  async function viewPlayer(pid) {
    const p = D.players[pid];
    const sq = squadOf[pid];
    if (!p && !sq) {
      $app.innerHTML = `<div class="card"><h2>Player not found</h2><a href="#/players">Back to players</a></div>`;
      return;
    }
    const events = L.eventsFor(pid, D.availability);
    const shifts = D.roles.filter(r => r.pid === pid);
    const notes = D.notes.filter(n => n.pid === pid);
    const pr = rounds16(pid);
    const career = p ? Object.values(p.s).reduce((t, a) => ({ sc: t.sc + a.sc, m: t.m + a.m }), { sc: 0, m: 0 }) : { sc: 0, m: 0 };
    const playerSeasons = p ? Object.keys(p.s).sort() : [];
    const latestPlayed = playerSeasons[playerSeasons.length - 1];

    $app.innerHTML = `
      <p><a href="#/players">← Players</a></p>
      <div class="row"><h2 style="margin:0">${esc(name(pid))}</h2>${squadButton(pid)}
        ${sq ? team(sq.team) : `<span class="pill">not in a BBL|16 squad</span>`}
        ${sq && sq.os ? `<span class="pill os">Overseas · ${esc(sq.os)}</span>` : ''}
        ${sq && sq.c ? '<span class="pill ok">Captain</span>' : ''}
        ${sq && sq.new ? '<span class="pill">No BBL history</span>' : ''}</div>
      <div class="stats" style="margin-top:12px">
        <div class="stat"><span class="muted">Proj (last 2 seasons)</span><b>${fix(proj(pid))}</b></div>
        <div class="stat"><span class="muted">${esc(latestPlayed || 'Last season')} avg</span><b>${latestPlayed ? fix(p.s[latestPlayed].sc / p.s[latestPlayed].m) : '–'}</b></div>
        <div class="stat"><span class="muted">Career avg</span><b>${career.m ? fix(career.sc / career.m) : '–'}</b></div>
        <div class="stat"><span class="muted">Last 5 avg</span><b id="last5">–</b></div>
        <div class="stat"><span class="muted">BBL matches</span><b>${career.m}</b></div>
      </div>
      <div id="spark" class="card hidden"></div>
      ${events.length || shifts.length || notes.length ? `<h3>News and availability</h3><div class="card feed">
        ${events.map(e => `<div class="item"><span class="date">${shortDay(e.start)}–${shortDay(e.end)}</span><span><span class="pill no">Unavailable</span> ${esc(e.name)} ${e.verified ? '' : '<span class="pill">dates unverified</span>'}</span></div>`).join('')}
        ${shifts.map(s => `<div class="item"><span class="date">${newsDay(s.date)}</span><span>${esc(s.text)}</span></div>`).join('')}
        ${notes.map(n => `<div class="item"><span class="date">${newsDay(n.date)}</span><span>${esc(n.text)} <span class="muted">${esc(n.source || '')}</span></span></div>`).join('')}
      </div>` : ''}
      ${sq ? `<h3>BBL|16 games</h3>${draftBanner()}<div class="scroll"><table>
        <thead><tr><th class="l">Round</th><th class="l">Matches</th><th>Playing</th></tr></thead>
        <tbody>${leagueRounds.map(r => {
          const games = grid[sq.team][r.round];
          const x = pr[r.round];
          return `<tr><td class="l">${roundLabel(r)}</td>
            <td class="l">${games.map(m => `${x.missed.includes(m) ? '<s>' : ''}${esc(when(m.start))} ${m.home === sq.team ? 'v' : '@'} ${team(m.home === sq.team ? m.away : m.home)}${x.missed.includes(m) ? '</s>' : ''}`).join('<br>') || '<span class="muted">Bye</span>'}</td>
            <td class="cell ${x.available === 0 ? 'g0' : x.available >= 2 ? 'g2' : ''}">${x.available}</td></tr>`;
        }).join('')}</tbody></table></div>` : ''}
      ${sq ? `<h3>Other competitions</h3><div id="else" class="muted">Loading…</div>` : ''}
      ${p ? `<h3>BBL seasons</h3><div class="scroll"><table>
        <thead><tr><th class="l">Season</th><th class="l">Team</th><th>M</th><th>SC avg</th><th>SC</th><th>Runs</th><th>Inn</th><th>NO</th><th>HS</th><th>Avg</th><th>SR</th><th>50/100</th><th>Overs</th><th>Wkts</th><th>Econ</th><th>Dots</th><th>Mdn</th><th>Ct</th><th>St</th><th>RO</th></tr></thead>
        <tbody>${playerSeasons.slice().reverse().map(s => {
          const a = p.s[s];
          const x = L.seasonLine(a);
          return `<tr><td class="l">${esc(s)}</td><td class="l">${team(a.t)}</td><td>${a.m}</td><td><b>${fix(x.avg)}</b></td><td>${a.sc}</td>
            <td>${a.r}</td><td>${a.inn}</td><td>${a.no}</td><td>${a.hs}</td><td>${fix(x.batAvg)}</td><td>${fix(x.sr, 0)}</td><td>${a.fifty}/${a.hund}</td>
            <td>${a.lb ? x.overs : ''}</td><td>${a.lb ? a.wk : ''}</td><td>${a.lb ? fix(x.econ, 2) : ''}</td><td>${a.lb ? a.dots : ''}</td><td>${a.lb ? a.mdn : ''}</td>
            <td>${a.ct}</td><td>${a.st}</td><td>${a.ro}</td></tr>`;
        }).join('')}</tbody></table></div>
        <h3>Match log</h3><div id="log" class="muted">Loading matches…</div>
        <h3>By venue</h3><div id="venues" class="muted">Loading…</div>` : ''}`;

    if (sq) renderElsewhere(pid, sq);
    if (!p) return;
    const recentSeasons = playerSeasons.slice(-2);
    async function renderLog(which) {
      const log = L.playerLog(pid, await Promise.all(which.map(season)));
      const recent = log.slice(-5);
      document.getElementById('last5').textContent = recent.length ? fix(recent.reduce((t, g) => t + g.sc, 0) / recent.length) : '–';
      const last20 = log.slice(-20).map(g => g.sc);
      const spark = document.getElementById('spark');
      if (last20.length > 1) {
        spark.classList.remove('hidden');
        spark.innerHTML = `<span class="muted">SC points, last ${last20.length} games (max ${Math.max(...last20)})</span><br>
          <svg class="spark" width="100%" height="48" viewBox="0 0 300 48" preserveAspectRatio="none"><path d="${L.sparkPath(last20, 300, 44)}" fill="none" stroke="#14213d" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
      }
      const more = which.length < playerSeasons.length;
      document.getElementById('log').outerHTML = `<div id="log"><div class="scroll"><table>
        <thead><tr><th class="l">Date</th><th class="l">Opp</th><th class="l">Venue</th><th>Pos</th><th>Bat</th><th>Bowl</th><th>Field</th><th>SC</th></tr></thead>
        <tbody>${log.slice().reverse().map(g => `<tr>
          <td class="l">${esc(g.date)}${g.final ? ' <span class="pill">final</span>' : ''}</td><td class="l">${team(g.opp)}</td><td class="l">${esc((g.venue || '').split(',')[0])}</td>
          <td>${g.bat_pos || ''}</td>
          <td>${g.batted ? `${g.r}${g.out ? '' : '*'} (${g.bf})` : '<span class="muted">dnb</span>'}</td>
          <td>${g.lb ? `${L.overs(g.lb)}-${g.mdn}-${g.rc}-${g.wk}` : ''}</td>
          <td>${[g.ct && `${g.ct}ct`, g.st && `${g.st}st`, g.ro && `${g.ro}ro`].filter(Boolean).join(' ')}</td>
          <td><b>${g.sc}</b></td></tr>`).join('')}</tbody></table></div>
        ${more ? `<p><button id="more">Show all ${playerSeasons.length} seasons</button></p>` : ''}</div>`;
      if (more) document.getElementById('more').addEventListener('click', () => renderLog(playerSeasons));
      const v = L.venueSplits(log);
      document.getElementById('venues').outerHTML = `<div id="venues" class="scroll"><table>
        <thead><tr><th class="l">Venue</th><th>M</th><th>SC avg</th></tr></thead>
        <tbody>${v.map(x => `<tr><td class="l">${esc(x.venue)}</td><td>${x.m}</td><td>${fix(x.avg)}</td></tr>`).join('')}</tbody></table>
        <p class="muted">From the ${which.length === playerSeasons.length ? 'whole career' : `${which.join(' and ')} seasons`}.</p></div>`;
    }
    await renderLog(recentSeasons);
  }

  const GROUPS = { t20: 'T20', od: 'One-day', fc: 'First-class' };

  async function renderElsewhere(pid, sq) {
    const e = await elsewhere();
    const el = document.getElementById('else');
    if (!el) return;
    const x = e.players[pid];
    if (!x) {
      el.textContent = 'No games found in internationals, the Sheffield Shield, the One-Day Cup or the franchise T20 leagues.';
      return;
    }
    const codes = Object.keys(e.comps).filter(c => x.c[c]);
    const groups = Object.keys(GROUPS).filter(g => codes.some(c => e.comps[c].g === g));
    const st = { g: groups.includes('t20') ? 't20' : groups[0], all: false };
    const cells = (a, sc) => {
      const v = L.aggLine(a);
      return `<td>${a.m}</td><td>${sc && a.scm ? `<b>${fix(v.scAvg)}</b>` : ''}</td><td>${a.r}</td><td>${a.inn}</td><td>${a.no}</td><td>${v.hs}</td>
        <td>${fix(v.batAvg)}</td><td>${fix(v.sr, 0)}</td><td>${a.f50}/${a.h100}</td>
        <td>${a.lb ? v.overs : ''}</td><td>${a.lb ? a.wk : ''}</td><td>${v.bb}</td><td>${a.lb ? fix(v.bowlAvg) : ''}</td><td>${a.lb ? fix(v.econ, 2) : ''}</td>
        <td>${a.ct}</td><td>${a.st}</td>`;
    };
    function render() {
      const y = x.y[st.g];
      const rows = codes.filter(c => e.comps[c].g === st.g).map(c => {
        const comp = e.comps[c];
        const seasonKeys = Object.keys(x.c[c]).sort().reverse();
        const span = seasonKeys.length > 1 ? `${seasonKeys[seasonKeys.length - 1]}–${seasonKeys[0]}` : seasonKeys[0];
        return `<tr><td class="l"><b>${esc(comp.name)}</b></td><td class="l">${esc(span)}</td>${cells(L.sumAggs(seasonKeys.map(s => x.c[c][s])), comp.sc)}</tr>` +
          (st.all && seasonKeys.length > 1 ? seasonKeys.map(s => `<tr><td></td><td class="l">${esc(s)}</td>${cells(x.c[c][s], comp.sc)}</tr>`).join('') : '');
      }).join('');
      el.className = '';
      el.innerHTML = `
        <div class="row" style="margin-bottom:8px">${groups.map(g => `<button data-g="${g}"${g === st.g ? ' class="on"' : ''}>${GROUPS[g]}</button>`).join('')}
          <button data-all>${st.all ? 'Hide' : 'Show'} seasons</button></div>
        <div class="scroll"><table class="pin">
          <thead><tr><th class="l">Competition</th><th class="l">Seasons</th><th>M</th><th>SC avg</th><th>Runs</th><th>Inn</th><th>NO</th><th>HS</th><th>Bat avg</th><th>SR</th><th>50/100</th><th>Overs</th><th>Wkts</th><th>Best</th><th>Bowl avg</th><th>Econ</th><th>Ct</th><th>St</th></tr></thead>
          <tbody><tr class="gx"><td class="l"><b>Since ${esc(monthYear(e.since))}</b></td><td class="l muted">all ${GROUPS[st.g]}</td>${y ? cells(y, st.g === 't20') : '<td colspan="16" class="l muted">No games</td>'}</tr>${rows}</tbody></table></div>
        <h3>Last ${x.f.length} games elsewhere</h3>
        <div class="scroll"><table>
          <thead><tr><th class="l">Date</th><th class="l">Competition</th><th>Bat</th><th>Bowl</th><th>SC</th><th class="l">Opponent</th></tr></thead>
          <tbody>${x.f.slice().reverse().map(f => `<tr><td class="l">${esc(yearDay(f.d))}</td><td class="l">${esc(e.comps[f.c].name)}</td>
            <td>${f.b.length ? esc(L.battingText(f.b)) : '<span class="muted">dnb</span>'}</td><td>${esc(L.bowlingText(f.w))}</td><td>${f.sc != null ? `<b>${f.sc}</b>` : ''}</td>
            <td class="l">${esc(f.o)}</td></tr>`).join('')}</tbody></table></div>
        <p class="muted">SC avg here is SC-equivalent: the BBL scoring table applied to T20 games elsewhere. It isn't given for The Hundred (5-ball overs), one-day or first-class cricket.
          ${sq.cs ? `Matched by name to Cricsheet's ${esc(x.n)}.` : ''}</p>`;
    }
    el.addEventListener('click', ev => {
      const b = ev.target.closest('button');
      if (!b) return;
      if (b.dataset.g) st.g = b.dataset.g; else st.all = !st.all;
      render();
    });
    render();
  }

  // ---------- planner ----------
  function viewPlanner(params) {
    const sel = Number(params.get('r')) || null;
    const squad = mySquad().filter(pid => squadOf[pid] || D.players[pid]);
    const entries = squad.map(pid => ({ pid, avg: proj(pid), team: squadOf[pid] && squadOf[pid].team, rounds: rounds16(pid) }))
      .sort((a, b) => (a.team || 'ZZZ').localeCompare(b.team || 'ZZZ') || (b.avg ?? 0) - (a.avg ?? 0));
    const selRound = leagueRounds.find(r => r.round === sel);
    const cls = n => (n === 0 ? 'g0' : n >= 3 ? 'g3' : n === 2 ? 'g2' : '');

    $app.innerHTML = `
      <h2>Doubles and byes</h2>${draftBanner()}
      <div class="scroll"><table class="pin">
        <thead><tr><th class="l">Team</th>${leagueRounds.map(r => `<th><a href="#/planner?r=${r.round}">${roundLabel(r)}</a></th>`).join('')}<th>Total</th></tr></thead>
        <tbody>${L.TEAMS.map(t => `<tr><td class="l">${team(t)}</td>${leagueRounds.map(r => {
          const g = grid[t][r.round];
          const opp = g.map(m => `${m.home === t ? 'v' : '@'} ${m.home === t ? m.away : m.home} ${day(L.localDate(m.start))}`).join('\n');
          return `<td class="cell ${cls(g.length)}" title="${esc(opp || 'Bye')}">${g.length}</td>`;
        }).join('')}<td>${leagueRounds.reduce((s, r) => s + grid[t][r.round].length, 0)}</td></tr>`).join('')}</tbody>
      </table></div>
      <p class="muted">Green = double, dark green = triple, red = bye. Hover a cell for opponents, or tap a round heading for its matches.</p>
      ${selRound ? `<div class="card"><b>Round ${selRound.round}</b> · ${day(selRound.start)} – ${day(selRound.end)}
        <div class="scroll"><table><tbody>${D.fixture.filter(m => m.stage === 'league' && L.roundOf(L.localDate(m.start), leagueRounds) === selRound).map(m => `
          <tr><td class="l">${esc(when(m.start))}</td><td class="l">${team(m.home)} v ${team(m.away)}</td><td class="l muted">${esc(m.venue ? `${m.venue.name}, ${m.venue.city}` : 'TBC')}</td></tr>`).join('')}
        </tbody></table></div></div>` : ''}
      <h2 style="margin-top:24px">My squad</h2>
      ${entries.length ? `<div class="scroll"><table>
        <thead><tr><th></th><th class="l">Player</th><th class="l">Team</th><th>Proj</th>${leagueRounds.map(r => `<th>R${r.round}</th>`).join('')}<th>Games</th></tr></thead>
        <tbody>${entries.map(e => `<tr><td>${squadButton(e.pid).replace('<button', '<button data-rerender="1"')}</td>
          <td class="l name">${link(e.pid)}</td><td class="l">${e.team ? team(e.team) : '<span class="pill no">no club</span>'}</td><td>${fix(e.avg)}</td>
          ${leagueRounds.map(r => {
            const x = e.rounds[r.round];
            if (!x) return '<td class="cell g0">0</td>';
            const missed = x.missed.length ? `Unavailable for ${x.missed.length} of ${x.games}` : '';
            return `<td class="cell ${x.missed.length ? 'gx' : cls(x.available)}" title="${esc(missed)}">${x.available}${x.missed.length ? `/${x.games}` : ''}</td>`;
          }).join('')}
          <td>${Object.values(e.rounds).reduce((s, x) => s + x.available, 0)}</td></tr>`).join('')}</tbody>
        <tfoot>
          <tr><th class="l" colspan="4">Players with a game</th>${leagueRounds.map(r => `<th>${entries.filter(e => e.rounds[r.round] && e.rounds[r.round].available).length}</th>`).join('')}<th></th></tr>
          <tr><th class="l" colspan="4">Captain options (proj × games)</th>${leagueRounds.map(r => `<td class="l" style="font-size:.8rem;white-space:normal;min-width:110px">${L.captainPicks(entries, r.round).map(c => `${esc(name(c.pid))} <span class="muted">${fix(c.value, 0)}</span>`).join('<br>') || '–'}</td>`).join('')}<td></td></tr>
        </tfoot></table></div>
        <p class="muted">A cell like 1/2 means the player misses one of two games for a listed clash. Proj is the last-two-seasons SC average.</p>`
      : `<div class="card">Your squad is empty. Add players with the <b>+</b> button on the <a href="#/players">Players</a> tab. It's saved on this device only.</div>`}`;
  }

  // ---------- availability ----------
  function viewAvailability() {
    const evs = D.availability.events.slice().sort((a, b) => a.start.localeCompare(b.start));
    const startD = [D.rounds.rounds[0].start, ...evs.map(e => e.start)].sort()[0];
    const endD = [D.rounds.rounds[D.rounds.rounds.length - 1].end, ...evs.map(e => e.end)].sort().pop();
    const t0 = Date.parse(startD), span = Date.parse(endD) + 864e5 - t0;
    const pos = (s, e) => `left:${(100 * (Date.parse(s) - t0) / span).toFixed(2)}%;width:${(100 * (Date.parse(e) + 864e5 - Date.parse(s)) / span).toFixed(2)}%`;
    const affected = D.availability.links.filter(l => l.pid).map(l => {
      const ev = evs.find(e => e.id === l.event);
      const sq = squadOf[l.pid];
      const games = sq ? Object.values(grid[sq.team]).flat().filter(m => { const d = L.localDate(m.start); return ev.start <= d && d <= ev.end; }) : [];
      return { ...l, ev, sq, games };
    });
    $app.innerHTML = `
      <h2>Availability</h2>
      <p class="muted">International duty and clashing leagues against the BBL|16 rounds. Hatched bars have dates we haven't confirmed yet.</p>
      <div class="timeline scroll"><div style="min-width:640px">
        <div class="tl-label muted">Rounds</div>
        <div class="tl-row">${D.rounds.rounds.map(r => `<div class="tl-bar k-round" style="${pos(r.start, r.end)}" title="${esc(`${day(r.start)} – ${day(r.end)}`)}">${r.finals ? 'Finals' : 'R' + r.round}</div>`).join('')}</div>
        ${evs.map(e => `<div class="tl-label">${esc(e.name)} <span class="muted">${shortDay(e.start)}–${shortDay(e.end)}</span> ${e.verified ? '<span class="pill ok">verified</span>' : '<span class="pill">unverified</span>'}</div>
          <div class="tl-row"><div class="tl-bar k-${esc(e.kind)}${e.verified ? '' : ' unverified'}" style="${pos(e.start, e.end)}"></div></div>`).join('')}
      </div></div>
      <h3>Players affected</h3>
      ${affected.length ? `<div class="scroll"><table>
        <thead><tr><th class="l">Player</th><th class="l">Team</th><th class="l">Reason</th><th>Games missed</th><th class="l">Matches</th></tr></thead>
        <tbody>${affected.map(a => `<tr><td class="l name">${link(a.pid)}</td><td class="l">${a.sq ? team(a.sq.team) : ''}</td><td class="l">${esc(a.ev.name)}</td>
          <td>${a.games.length}</td><td class="l muted">${a.games.map(m => `${a.sq.team === m.home ? 'v' : '@'} ${m.home === a.sq.team ? m.away : m.home} ${shortDay(L.localDate(m.start))}`).join(', ')}</td></tr>`).join('')}</tbody></table></div>` : ''}
      <p class="muted">Test and overseas-league squads aren't named yet. Players are linked to an event as each squad is announced.</p>`;
  }

  // ---------- roles ----------
  function viewRoles(params) {
    const scope = params.get('scope') || 'all';
    const kind = params.get('kind') || '';
    const kinds = { '': 'Everything', transfer: 'Club moves', bat: 'Batting order', bowl: 'Bowling', note: 'News' };
    const mine = new Set(mySquad());
    const items = [
      ...D.roles.map(r => ({ ...r, group: r.kind.startsWith('bat') || r.kind === 'opener' ? 'bat' : r.kind.startsWith('bowl') ? 'bowl' : r.kind })),
      ...D.notes.map(n => ({ ...n, group: 'note' })),
    ].filter(i => (!kind || i.group === kind) && (scope === 'all' || mine.has(i.pid)))
      .sort((a, b) => b.date.localeCompare(a.date));
    const q = (k, v) => { const p = new URLSearchParams({ scope, kind }); p.set(k, v); return '#/roles?' + p; };
    $app.innerHTML = `
      <h2>Roles and news</h2>
      <div class="row" style="margin-bottom:10px">
        ${Object.entries(kinds).map(([k, label]) => `<a class="btn" href="${q('kind', k)}"><button class="${k === kind ? 'on' : ''}">${label}</button></a>`).join('')}
        <span style="flex:1"></span>
        <a href="${q('scope', scope === 'all' ? 'mine' : 'all')}"><button class="${scope === 'mine' ? 'on' : ''}">My squad only</button></a>
      </div>
      <p class="muted">Role shifts are detected automatically by comparing each player's last 3 games with their earlier games over the last 3 seasons.</p>
      <div class="card feed">${items.map(i => `<div class="item">
        <span class="date">${newsDay(i.date)}</span>
        <span>${i.team || (squadOf[i.pid] && squadOf[i.pid].team) ? team(i.team || squadOf[i.pid].team) : ''} ${i.pid ? `<b>${link(i.pid)}</b>` : ''} ${esc(i.text)}</span>
      </div>`).join('') || '<p class="muted">Nothing here yet.</p>'}</div>`;
  }

  // ---------- matches ----------
  const CA = 'https://apiv2.cricket.com.au/web/views/scorecard?jsconfig=eccn%3Atrue&format=json&fixtureId=';
  const FORECAST = 'https://api.open-meteo.com/v1/forecast?hourly=precipitation_probability,precipitation&timezone=GMT&forecast_days=16';
  const FORECAST_DAYS = 15;
  const CAPTAIN_KEY = 'scbbl-captain';
  const lazy = f => { let p; return () => p || (p = json(`data/${f}.json`)); };
  const climate = lazy('climate'), scoring = lazy('scoring'), idmap = lazy('idmap');
  const forecasts = {}, cards = {};
  let view = 0, timer = null;

  const roundOfMatch = m => L.roundOf(L.localDate(m.start), D.rounds.rounds);
  const roundName = r => (r ? (r.finals ? 'Finals' : `R${r.round}`) : '');
  // From the toss (~T-30) until well after the scheduled finish, allowing for delays.
  const near = m => Date.now() > Date.parse(m.start) - 90 * 60e3 && Date.now() < Date.parse(m.end) + 3 * 3600e3;

  function forecast(v) {
    const k = `${v.lat},${v.lon}`;
    return forecasts[k] || (forecasts[k] = fetch(`${FORECAST}&latitude=${v.lat}&longitude=${v.lon}`)
      .then(r => (r.ok ? r.json() : null))
      .then(j => j && Object.fromEntries(j.hourly.time.map((t, i) => [t, { p: j.hourly.precipitation_probability[i], mm: j.hourly.precipitation[i] }])))
      .catch(() => null));
  }

  async function rainFor(m) {
    if (!m.venue || Date.parse(m.end) < Date.now()) return null;
    if (Date.parse(m.start) - Date.now() < FORECAST_DAYS * 864e5) {
      const f = await forecast(m.venue);
      const hours = f && L.windowHours(m.start, m.end).map(h => f[h] && { h, ...f[h] });
      if (hours && hours.every(Boolean)) return { kind: 'forecast', hours, ...L.rainRisk(hours) };
    }
    const c = L.climateRisk((await climate())[m.id]);
    return c && { kind: 'climate', ...c };
  }

  const RAIN_CLS = { Low: 'ok', Med: 'warn', High: 'no' };
  function rainPill(r) {
    if (!r) return '';
    const [txt, title] = r.kind === 'forecast'
      ? [`${r.maxP}% · ${fix(r.mm)} mm`, 'Open-Meteo forecast over the match window: highest hourly chance of rain, and total rain']
      : [`${Math.round(100 * r.wet)}% hist.`, 'Share of the same window over the past 10 years (±3 days) with at least 1 mm of rain'];
    return `<span class="pill ${RAIN_CLS[r.level]}" title="${title}">Rain ${r.level}</span> <span class="muted">${txt}</span>`;
  }

  // cricket.com.au caches the scorecard for 30 s, so there's no point asking more often.
  function card(id) {
    const c = cards[id];
    if (c && Date.now() - c.t < 25e3) return c.p;
    const p = fetch(CA + id).then(r => {
      if (!r.ok) throw new Error(`cricket.com.au HTTP ${r.status}`);
      return r.json();
    });
    cards[id] = { t: Date.now(), p };
    p.catch(() => { delete cards[id]; });
    return p;
  }

  const teamCode = (c, m, teamId) => (teamId === (c.fixture || {}).homeTeamId ? m.home : m.away);
  function scoreText(c, m) {
    return ((c.fixture && c.fixture.innings) || [])
      .map(i => `${teamCode(c, m, i.battingTeamId)} ${i.runsScored}/${i.numberOfWicketsFallen} (${i.oversBowled})`).join(' · ');
  }
  function statusText(c) {
    const f = c.fixture || {};
    return f.resultText || (f.isLive || f.isInProgress ? 'Live' : f.tossResult || '');
  }

  function cardLines(c, m, ids, table) {
    return L.caLines(c).map(l => {
      const code = teamCode(c, m, l.team);
      return { ...l, code, pid: L.matchPid(l, ids, D.squads.teams[code] || []), sc: L.scPoints(l, table) };
    });
  }
  function captains() {
    try { return JSON.parse(localStorage.getItem(CAPTAIN_KEY)) || {}; } catch { return {}; }
  }
  function squadTotal(lines, cap) {
    const mine = new Set(mySquad());
    return lines.filter(l => mine.has(l.pid)).reduce((t, l) => t + l.sc * (l.pid === cap ? 2 : 1), 0);
  }

  function viewMatches(params) {
    const all = params.get('all') === '1';
    const list = D.fixture.slice().sort((a, b) => a.start.localeCompare(b.start))
      .filter(m => all || Date.parse(m.end) + 3 * 3600e3 > Date.now());
    $app.innerHTML = `
      <h2>Matches</h2>
      <div class="row" style="margin-bottom:10px"><a href="#/matches${all ? '' : '?all=1'}"><button class="${all ? 'on' : ''}">Show completed</button></a></div>
      <p class="muted">Rain risk comes from the Open-Meteo forecast within ${FORECAST_DAYS} days of a match. Before that it's how often the same window has been wet over the past 10 years. Tap a match for team sheets and live SC points.</p>
      <div class="scroll"><table id="mtable">
        <thead><tr><th class="l">When (AEDT)</th><th class="l">Round</th><th class="l">Match</th><th class="l">Venue</th><th class="l">Rain</th><th class="l">Score</th></tr></thead>
        <tbody>${list.map(m => `<tr data-id="${m.id}">
          <td class="l">${esc(when(m.start))}</td><td class="l">${roundName(roundOfMatch(m))}</td>
          <td class="l name"><a href="#/match/${m.id}">${team(m.home)} v ${team(m.away)}</a> <span class="muted">${esc(m.name)}</span></td>
          <td class="l muted">${esc(m.venue ? m.venue.city : 'TBC')}</td><td class="l rain"></td><td class="l status"></td></tr>`).join('')
          || '<tr><td colspan="6" class="l muted">No matches left this season.</td></tr>'}</tbody></table></div>`;
    const cell = (m, cls) => document.querySelector(`#mtable tr[data-id="${m.id}"] .${cls}`);
    for (const m of list) {
      rainFor(m).then(r => { const el = cell(m, 'rain'); if (el) el.innerHTML = rainPill(r); });
      if (near(m)) {
        card(m.id).then(c => {
          const el = cell(m, 'status');
          if (el) el.innerHTML = `${esc(scoreText(c, m))} <span class="muted">${esc(statusText(c))}</span>`;
        }).catch(() => {});
      }
    }
  }

  function renderRain(r) {
    const el = document.getElementById('rain');
    if (!el || !r) return;
    if (r.kind === 'climate') {
      el.innerHTML = `<div class="card">${rainPill(r)}<p class="muted" style="margin:6px 0 0">Too far out for a forecast. Over the past 10 years (±3 days), ${Math.round(100 * r.wet)}% of these match windows had at least 1 mm of rain and ${Math.round(100 * r.heavy)}% had 5 mm or more.</p></div>`;
      return;
    }
    const hour = h => new Date(Date.parse(h + ':00Z') - 3600e3).toLocaleTimeString('en-AU', { timeZone: 'Australia/Sydney', hour: 'numeric' });
    el.innerHTML = `<div class="card">${rainPill(r)}
      <div class="scroll" style="margin-top:6px"><table><tbody>
        <tr><th class="l">From (AEDT)</th>${r.hours.map(h => `<th>${esc(hour(h.h))}</th>`).join('')}</tr>
        <tr><td class="l muted">Chance of rain</td>${r.hours.map(h => `<td class="${h.p >= 60 ? 'g0' : h.p >= 30 ? 'gx' : ''}">${h.p ?? '–'}%</td>`).join('')}</tr>
        <tr><td class="l muted">Rain (mm)</td>${r.hours.map(h => `<td>${fix(h.mm)}</td>`).join('')}</tr>
      </tbody></table></div><p class="muted" style="margin:6px 0 0">Open-Meteo forecast at the ground.</p></div>`;
  }

  function teamSheets(m) {
    const mine = new Set(mySquad());
    return `<div class="card"><b>XIs aren't named yet.</b> They appear at the toss, about 30 minutes before the start. Until then, here are the squads.</div>
      <div class="stats">${[m.home, m.away].filter(t => D.squads.teams[t]).map(t => `<div class="stat">${team(t)} <span class="muted">squad</span>
        ${D.squads.teams[t].map(r => `<div class="${mine.has(r.pid) ? 'mine' : ''}">${link(r.pid)}${r.c ? ' <span class="pill">C</span>' : ''}${r.os ? ` <span class="pill os">${esc(r.os)}</span>` : ''}</div>`).join('')}</div>`).join('')}</div>`;
  }

  function xiTable(lines, t, cap, roundNo, live) {
    const mine = new Set(mySquad());
    const rows = lines.filter(l => l.code === t).sort((a, b) => (a.bat_pos ?? 99) - (b.bat_pos ?? 99));
    const inXI = new Set(rows.map(l => l.pid));
    const out = (D.squads.teams[t] || []).filter(r => !inXI.has(r.pid));
    const badge = (on, s) => (on ? ` <span class="pill">${s}</span>` : '');
    return `<h3>${team(t)} XI</h3><div class="scroll"><table class="pin">
      <thead><tr><th class="l">Player</th><th></th><th>Bat</th><th>4s/6s</th><th>SR</th><th class="l">Out</th><th>Bowl</th><th>Dots</th><th>Econ</th><th>Field</th><th>SC</th></tr></thead>
      <tbody>${rows.map(l => {
        const isCap = l.pid && l.pid === cap;
        return `<tr class="${mine.has(l.pid) ? 'mine' : ''}">
        <td class="l name">${l.pid ? link(l.pid) : esc(l.name)}${badge(l.captain, 'capt')}${badge(l.keeper, 'WK')}${badge(l.db, 'DB')}${badge(l.df, 'DF')}</td>
        <td>${mine.has(l.pid) ? `<button class="cap${isCap ? ' on' : ''}" data-cap="${esc(l.pid)}" title="${isCap ? 'Remove as' : 'Make'} my captain for ${roundNo ? 'round ' + roundNo : 'this round'} (double points)">C</button>` : ''}</td>
        <td>${l.batted ? `${l.r}${l.out ? '' : '*'} (${l.bf})${live && l.batting ? ' <span class="pill ok">in</span>' : ''}` : ''}</td>
        <td>${l.batted ? `${l.f4}/${l.s6}` : ''}</td><td>${l.bf ? fix(100 * l.r / l.bf, 0) : ''}</td>
        <td class="l muted" style="white-space:normal;min-width:120px">${esc(l.how)}</td>
        <td>${l.lb ? `${L.overs(l.lb)}-${l.mdn}-${l.rc}-${l.wk}` : ''}</td><td>${l.lb ? l.dots : ''}</td><td>${l.lb ? fix(6 * l.rc / l.lb, 2) : ''}</td>
        <td>${[l.ct && `${l.ct}ct`, l.st && `${l.st}st`, l.ro && `${l.ro}ro`].filter(Boolean).join(' ')}</td>
        <td class="sc"><b>${isCap ? 2 * l.sc : l.sc}</b>${isCap ? ' <span class="muted">×2</span>' : ''}</td></tr>`;
      }).join('')}</tbody></table></div>
      ${out.length ? `<p class="muted">Not in the XI: ${out.map(r => `${mine.has(r.pid) ? '<span class="pill no">' : ''}${esc(r.n)}${mine.has(r.pid) ? '</span>' : ''}`).join(', ')}</p>` : ''}`;
  }

  async function viewMatch(id) {
    const m = D.fixture.find(x => String(x.id) === id);
    if (!m) {
      $app.innerHTML = `<div class="card"><h2>Match not found</h2><a href="#/matches">Back to matches</a></div>`;
      return;
    }
    const token = view;
    const r = roundOfMatch(m);
    const rkey = r ? String(r.round) : 'x';
    $app.innerHTML = `
      <p><a href="#/matches">← Matches</a></p>
      <div class="row"><h2 style="margin:0">${team(m.home)} v ${team(m.away)}</h2><span class="muted">${esc(m.name)}${r ? ` · ${r.finals ? 'Finals' : 'Round ' + r.round}` : ''}</span></div>
      <p class="muted">${esc(when(m.start))} AEDT · ${esc(m.venue ? `${m.venue.name}, ${m.venue.city}` : 'Venue TBC')}</p>
      <div id="rain"></div>
      <div id="live"><p class="muted">Loading the scorecard…</p></div>`;
    rainFor(m).then(x => { if (token === view) renderRain(x); });
    const [table, ids] = await Promise.all([scoring(), idmap()]);
    // The rest of the round: started matches only. Finished ones are fetched once, live ones every poll.
    const others = D.fixture.filter(x => x.id !== m.id && roundOfMatch(x) === r && r && Date.parse(x.start) < Date.now());
    const done = {};
    let last = null;

    async function roundTotal(lines, cap) {
      let t = squadTotal(lines, cap);
      for (const x of others) {
        const p = !near(x) && done[x.id] ? done[x.id] : (done[x.id] = card(x.id).catch(() => null));
        const c = await p;
        if (c) t += squadTotal(cardLines(c, x, ids, table), cap);
      }
      return t;
    }

    function draw(c) {
      const el = document.getElementById('live');
      if (!el || token !== view) return;
      const lines = cardLines(c, m, ids, table);
      const cap = captains()[rkey];
      const score = scoreText(c, m), status = statusText(c);
      el.innerHTML = `
        ${score || status ? `<div class="card"><b>${esc(score)}</b> <span class="muted">${esc(status)}</span></div>` : ''}
        ${lines.length ? `
          <div class="stats"><div class="stat"><span class="muted">My squad, this match</span><b id="mtotal">${squadTotal(lines, cap)}</b></div>
            <div class="stat"><span class="muted">My squad, ${r ? (r.finals ? 'finals' : 'round ' + r.round) : 'round'} so far</span><b id="rtotal">…</b></div></div>
          ${[m.home, m.away].map(t => xiTable(lines, t, cap, r && r.round, !(c.fixture && c.fixture.isCompleted))).join('')}
          <p class="muted">Unofficial: SC points computed from the cricket.com.au scorecard with the published scoring table. The official SuperCoach score can differ. A run-out is credited in full to the one fielder cricket.com.au names.${near(m) && !(c.fixture && c.fixture.isCompleted) ? ' Updates every 30 seconds.' : ''}</p>`
        : teamSheets(m)}`;
      if (lines.length) {
        roundTotal(lines, cap).then(t => { const x = document.getElementById('rtotal'); if (x && token === view) x.textContent = t; });
      }
    }

    async function tick() {
      if (token !== view) return;
      if (!last || document.visibilityState === 'visible') {
        try {
          last = await card(m.id);
          draw(last);
        } catch (err) {
          const el = document.getElementById('live');
          if (el && !last && token === view) el.innerHTML = `<div class="card">Couldn't load the scorecard from cricket.com.au (${esc(err.message)}).${near(m) ? ' Retrying every 30 seconds.' : ''}</div>`;
        }
      }
      if (token === view && near(m) && !(last && last.fixture && last.fixture.isCompleted)) timer = setTimeout(tick, 30e3);
    }

    $app.onclick = e => {
      const b = e.target.closest('[data-cap]');
      if (!b || !last) return;
      const caps = captains();
      if (caps[rkey] === b.dataset.cap) delete caps[rkey]; else caps[rkey] = b.dataset.cap;
      localStorage.setItem(CAPTAIN_KEY, JSON.stringify(caps));
      draw(last);
    };
    await tick();
  }

  // ---------- router ----------
  async function route() {
    view += 1;
    clearTimeout(timer);
    $app.onclick = null;
    const [path, query] = (location.hash || '#/').slice(1).split('?');
    const params = new URLSearchParams(query || '');
    const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
    const tab = { player: 'players', match: 'matches' }[parts[0]] || parts[0] || 'players';
    document.querySelectorAll('#tabs a').forEach(a => a.classList.toggle('on', a.dataset.tab === tab));
    try {
      if (parts[0] === 'player' && parts[1]) return await viewPlayer(parts[1]);
      if (parts[0] === 'matches') return viewMatches(params);
      if (parts[0] === 'match' && parts[1]) return await viewMatch(parts[1]);
      if (parts[0] === 'planner') return viewPlanner(params);
      if (parts[0] === 'availability') return viewAvailability();
      if (parts[0] === 'roles') return viewRoles(params);
      return viewPlayers(params);
    } catch (err) {
      $app.innerHTML = `<div class="card"><h2>Something went wrong</h2><p>${esc(err.message)}</p><a href="#/players">Back to players</a></div>`;
      console.error(err);
    }
  }

  async function init() {
    const files = ['players', 'fixture', 'squads', 'rounds', 'availability', 'roles', 'notes', 'meta'];
    const loaded = await Promise.all(files.map(f => json(`data/${f}.json`)));
    files.forEach((f, i) => { D[f] = loaded[i]; });
    seasons = D.meta.seasons.slice().sort();
    leagueRounds = D.rounds.rounds.filter(r => !r.finals);
    grid = L.teamRounds(D.fixture, leagueRounds);
    squadOf = {};
    for (const [t, rows] of Object.entries(D.squads.teams)) for (const r of rows) squadOf[r.pid] = { ...r, team: t };
    document.getElementById('built').textContent = `data ${D.meta.built.slice(0, 10)}`;
    window.addEventListener('hashchange', () => { window.scrollTo(0, 0); route(); });
    route();
  }

  init().catch(err => {
    $app.innerHTML = `<div class="card"><h2>Couldn't load the data</h2><p>${esc(err.message)}</p></div>`;
    console.error(err);
  });
  if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('sw.js');
})();

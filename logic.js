(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Logic = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Rounds are AEDT calendar days; all of BBL|16 falls inside daylight saving (UTC+11).
  const AEDT_MS = 11 * 3600 * 1000;
  const TEAMS = ['HEA', 'HUR', 'REN', 'SCO', 'SIX', 'STA', 'STR', 'THU'];

  function localDate(iso) {
    return new Date(Date.parse(iso) + AEDT_MS).toISOString().slice(0, 10);
  }

  function roundOf(day, rounds) {
    return rounds.find(r => r.start <= day && day <= r.end) || null;
  }

  function within(day, ev) {
    return ev.start <= day && day <= ev.end;
  }

  // team -> round number -> league matches that team plays in that round
  function teamRounds(fixture, rounds) {
    const grid = {};
    for (const t of TEAMS) grid[t] = Object.fromEntries(rounds.map(r => [r.round, []]));
    for (const m of fixture) {
      if (m.stage !== 'league') continue;
      const r = roundOf(localDate(m.start), rounds);
      if (!r) continue;
      for (const t of [m.home, m.away]) if (grid[t]) grid[t][r.round].push(m);
    }
    return grid;
  }

  function eventsFor(pid, availability) {
    const ids = new Set(availability.links.filter(l => l.pid === pid).map(l => l.event));
    return availability.events.filter(e => ids.has(e.id));
  }

  // Per round: games the player's team plays, and which of those clash with the player's events.
  function playerRounds(team, pid, grid, availability) {
    const evs = eventsFor(pid, availability);
    const out = {};
    for (const [round, games] of Object.entries(team && grid[team] ? grid[team] : {})) {
      const missed = games.filter(m => evs.some(e => within(localDate(m.start), e)));
      out[round] = { games: games.length, available: games.length - missed.length, missed };
    }
    return out;
  }

  function overs(balls) {
    return `${Math.floor(balls / 6)}.${balls % 6}`;
  }

  function seasonLine(a) {
    const outs = a.inn - a.no;
    return {
      avg: a.m ? a.sc / a.m : null,
      batAvg: outs ? a.r / outs : null,
      sr: a.bf ? 100 * a.r / a.bf : null,
      econ: a.lb ? 6 * a.rc / a.lb : null,
      overs: overs(a.lb),
    };
  }

  // SC average over the two latest seasons; falls back to the whole career under 3 games.
  function projAvg(player, seasons) {
    if (!player) return null;
    const sum = keys => keys.reduce((t, k) => {
      const a = player.s[k];
      return a ? { sc: t.sc + a.sc, m: t.m + a.m } : t;
    }, { sc: 0, m: 0 });
    let t = sum(seasons.slice(-2));
    if (t.m < 3) t = sum(Object.keys(player.s));
    return t.m ? t.sc / t.m : null;
  }

  // entries: [{pid, avg, rounds: {round: {available}}}] -> best captain options for a round
  function captainPicks(entries, round, n = 3) {
    return entries
      .filter(e => e.avg != null && e.rounds[round] && e.rounds[round].available > 0)
      .map(e => ({ ...e, value: e.avg * e.rounds[round].available }))
      .sort((a, b) => b.value - a.value)
      .slice(0, n);
  }

  function sparkPath(values, w, h) {
    if (values.length < 2) return '';
    const max = Math.max(...values, 1);
    const step = w / (values.length - 1);
    return values.map((v, i) => `${i ? 'L' : 'M'}${(i * step).toFixed(1)},${(h - (v / max) * h).toFixed(1)}`).join('');
  }

  function venueSplits(log) {
    const by = {};
    for (const g of log) {
      const v = by[g.venue] || (by[g.venue] = { venue: g.venue, m: 0, sc: 0 });
      v.m += 1;
      v.sc += g.sc;
    }
    return Object.values(by).map(v => ({ ...v, avg: v.sc / v.m })).sort((a, b) => b.m - a.m || b.avg - a.avg);
  }

  // A player's match lines from loaded season files, oldest first.
  function playerLog(pid, seasonFiles) {
    const log = [];
    for (const matches of seasonFiles) {
      for (const m of matches) {
        const l = m.lines.find(x => x.pid === pid && !x.sub);
        if (l) log.push({ ...l, id: m.id, date: m.date, venue: m.venue, opp: m.teams.find(t => t !== l.team), final: m.final });
      }
    }
    return log.sort((a, b) => a.date.localeCompare(b.date));
  }

  return { TEAMS, localDate, roundOf, teamRounds, eventsFor, playerRounds, overs, seasonLine, projAvg, captainPicks, sparkPath, venueSplits, playerLog };
});

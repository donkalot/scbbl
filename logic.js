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

  // A link marked likely is a squad not yet named; it still counts as missed, so plans stay conservative.
  function eventsFor(pid, availability) {
    const likely = new Map(availability.links.filter(l => l.pid === pid).map(l => [l.event, !!l.likely]));
    return availability.events.filter(e => likely.has(e.id)).map(e => ({ ...e, likely: likely.get(e.id) }));
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

  // Seats players [{pid, pos}] in SC's squad slots. Own positions come first (augmenting paths, so a WKP/BAT
  // can move to free a BAT seat); the FLX seats then take anyone left over.
  function slotFit(players, positions) {
    const slots = [];
    for (const [pos, r] of Object.entries(positions)) if (pos !== 'FLX') for (let i = 0; i < r.squad; i++) slots.push({ pos, pid: null });
    const holder = slots.map(() => -1);
    const place = (i, seen) => {
      for (let s = 0; s < slots.length; s++) {
        if (seen[s] || !players[i].pos.includes(slots[s].pos)) continue;
        seen[s] = true;
        if (holder[s] < 0 || place(holder[s], seen)) { holder[s] = i; return true; }
      }
      return false;
    };
    const left = players.map((_, i) => i).filter(i => !place(i, []));
    holder.forEach((i, s) => { if (i >= 0) slots[s].pid = players[i].pid; });
    for (let i = 0; i < ((positions.FLX && positions.FLX.squad) || 0); i++) {
      const p = left.shift();
      slots.push({ pos: 'FLX', pid: p == null ? null : players[p].pid });
    }
    return { slots, unplaced: left.map(i => players[i].pid) };
  }

  // Pool players [{pid, pos, price}] within budget who still leave every squad member a seat.
  function fitting(squad, pool, positions, budget) {
    return pool.filter(p => p.price <= budget && slotFit([...squad, p], positions).unplaced.length === 0);
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

  const SUMMED = ['m', 'inn', 'no', 'f50', 'h100', 'w5', 'r', 'bf', 'f4', 's6', 'lb', 'rc', 'wk', 'ct', 'st', 'ro'];

  // Career totals for one competition from its season aggregates (data/elsewhere.json).
  function sumAggs(aggs) {
    const t = { hs: 0, hsn: false, bb: null };
    for (const k of SUMMED) t[k] = 0;
    for (const a of aggs) {
      for (const k of SUMMED) t[k] += a[k] || 0;
      if (a.scm) { t.sc = (t.sc || 0) + a.sc; t.scm = (t.scm || 0) + a.scm; }
      if (a.hs > t.hs || (a.hs === t.hs && a.hsn)) { t.hs = a.hs; t.hsn = a.hsn; }
      if (a.bb && (!t.bb || a.bb[0] > t.bb[0] || (a.bb[0] === t.bb[0] && a.bb[1] < t.bb[1]))) t.bb = a.bb;
    }
    return t;
  }

  function aggLine(a) {
    const outs = a.inn - a.no;
    return {
      scAvg: a.scm ? a.sc / a.scm : null,
      batAvg: outs ? a.r / outs : null,
      sr: a.bf ? 100 * a.r / a.bf : null,
      econ: a.lb ? 6 * a.rc / a.lb : null,
      bowlAvg: a.wk ? a.rc / a.wk : null,
      overs: overs(a.lb),
      hs: a.inn ? `${a.hs}${a.hsn ? '*' : ''}` : '',
      bb: a.bb ? `${a.bb[0]}/${a.bb[1]}` : '',
    };
  }

  // Per-innings [runs, balls, out] -> "45* (32)" for one innings, "12 & 45*" for two.
  function battingText(b) {
    if (!b.length) return '';
    if (b.length === 1) return `${b[0][0]}${b[0][2] ? '' : '*'} (${b[0][1]})`;
    return b.map(([r, , out]) => `${r}${out ? '' : '*'}`).join(' & ');
  }
  const bowlingText = w => w.map(([, rc, wk]) => `${wk}/${rc}`).join(' & ');

  function band(v, bands, higherIsBetter) {
    const hit = bands.find(([edge]) => (higherIsBetter ? v >= edge : v <= edge));
    return hit ? hit[1] : 0;
  }
  const round2 = x => Math.round(x * 100) / 100;

  // Same as pipeline/scoring.py sc_points, so live and historical points agree.
  function scPoints(l, t) {
    const bat = t.batting, bwl = t.bowling, fld = t.fielding;
    let pts = l.r * bat.run;
    if (l.r >= bat.sr_min_runs && l.bf) pts += band(round2(100 * l.r / l.bf), bat.sr_bands, true);
    const ms = bat.milestones.find(([runs]) => l.r >= runs);
    if (ms) pts += ms[1];
    pts += l.wk * bwl.wicket + Math.floor(l.wk / bwl.haul_every) * bwl.haul_bonus;
    pts += l.mdn * bwl.maiden + l.dots * bwl.dot + (l.wd + l.nb) * bwl.extra;
    if (l.lb >= bwl.er_min_balls) pts += band(round2(6 * l.rc / l.lb), bwl.er_bands, false);
    const shared = l.ro - l.ro_solo;
    pts += l.ct * fld.catch + l.st * fld.stumping + l.ro_solo * fld.run_out + Math.floor(shared * fld.run_out / 2);
    return pts;
  }

  const FIELDED = { Caught: 'ct', 'Caught and bowled': 'ct', Stumped: 'st', RunOut: 'ro' };

  // cricket.com.au views/scorecard -> one line per player in the XIs, shaped like the Cricsheet lines.
  // CA names a single run-out fielder, so every run-out it lists counts as solo.
  // CA's dotBalls counts legal balls the batter didn't score off, byes and leg-byes included; SuperCoach's
  // dots exclude them. Counts those balls per bowler from CA ball-by-ball (views/comments) overs.
  function byeDots(balls) {
    const out = {};
    for (const b of balls || []) {
      if (b.bowlerPlayerId == null || b.isWide || b.isNoBall || b.runsScored) continue;
      if ((b.runsByes || 0) + (b.runsLegByes || 0) > 0) out[b.bowlerPlayerId] = (out[b.bowlerPlayerId] || 0) + 1;
    }
    return out;
  }

  function caLines(card, byes = {}) {
    const lines = new Map();
    for (const p of card.players || []) {
      lines.set(p.id, {
        ca: p.id, team: p.teamId, name: p.displayName || p.name, keeper: !!p.isWicketKeeper, captain: !!p.isCaptain,
        db: !!p.isDesignatedBatter, df: !!p.isDesignatedFielder,
        r: 0, bf: 0, f4: 0, s6: 0, out: false, batted: false, batting: false, bat_pos: null, how: '',
        lb: 0, rc: 0, wk: 0, dots: 0, mdn: 0, wd: 0, nb: 0, bowling: false, ct: 0, st: 0, ro: 0, ro_solo: 0,
      });
    }
    for (const inn of (card.fixture && card.fixture.innings) || []) {
      for (const b of inn.batsmen || []) {
        const l = lines.get(b.playerId);
        if (l && 'runsScored' in b) {
          Object.assign(l, { r: b.runsScored, bf: b.ballsFaced, f4: b.foursScored, s6: b.sixesScored, out: !!b.isOut,
                             batted: true, batting: !!b.isBatting, bat_pos: b.battingOrder, how: b.dismissalText || '' });
        }
        const f = FIELDED[b.dismissalTypeId] && lines.get(b.dismissedByPlayerId);
        if (f) {
          f[FIELDED[b.dismissalTypeId]] += 1;
          if (b.dismissalTypeId === 'RunOut') f.ro_solo += 1;
        }
      }
      for (const w of inn.bowlers || []) {
        const l = lines.get(w.playerId);
        if (!l) continue;
        Object.assign(l, { lb: w.totalBallsBowled, rc: w.runsConceded, wk: w.wicketsTaken, dots: w.dotBalls - (byes[w.playerId] || 0), mdn: w.maidensBowled,
                           wd: w.wideBalls, nb: w.noBalls, bowling: !!(w.isOnStrike || w.isNonStrike) });
      }
    }
    return [...lines.values()];
  }

  // Open-Meteo hourly forecast over the match window: [{p: % chance of rain, mm}] -> band.
  function rainRisk(hours) {
    if (!hours.length) return null;
    const maxP = Math.max(...hours.map(h => h.p ?? 0));
    const mm = hours.reduce((t, h) => t + (h.mm || 0), 0);
    const level = mm >= 3 || maxP >= 60 ? 'High' : mm >= 0.5 || maxP >= 30 ? 'Med' : 'Low';
    return { level, maxP, mm };
  }

  // data/climate.json entry: share of the same window in past years with at least 1 mm.
  function climateRisk(c) {
    if (!c || !c.n) return null;
    const wet = c.wet / c.n;
    return { level: wet >= 0.2 ? 'High' : wet >= 0.1 ? 'Med' : 'Low', wet, heavy: c.heavy / c.n };
  }

  // Open-Meteo labels each hour by its end, so label h covers (h-1, h].
  function windowHours(start, end) {
    const out = [];
    const s = Date.parse(start), e = Date.parse(end);
    for (let h = Math.floor(s / 3600e3) * 3600e3 + 3600e3; h - 3600e3 < e; h += 3600e3) out.push(new Date(h).toISOString().slice(0, 16));
    return out;
  }

  const normName = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z ]/g, ' ').split(/\s+/).filter(Boolean);

  // CA player -> our pid: the CA id map first, then surname plus first initial within that team's squad.
  function matchPid(line, idmap, squadRows) {
    if (idmap[line.ca]) return idmap[line.ca];
    const t = normName(line.name);
    const hits = squadRows.filter(r => {
      const s = normName(r.n);
      return s[s.length - 1] === t[t.length - 1] && s[0][0] === t[0][0];
    });
    return hits.length === 1 ? hits[0].pid : null;
  }

  return { TEAMS, localDate, roundOf, teamRounds, eventsFor, playerRounds, overs, seasonLine, projAvg, captainPicks, slotFit, fitting, sparkPath, venueSplits, playerLog,
           sumAggs, aggLine, battingText, bowlingText, scPoints, byeDots, caLines, rainRisk, climateRisk, windowHours, matchPid };
});

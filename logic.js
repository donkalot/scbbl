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
  // A link's from/until narrow the event for that player: called up mid-series, or released to play BBL.
  function eventsFor(pid, availability) {
    const mine = availability.links.filter(l => l.pid === pid);
    return availability.events.flatMap(e => mine.filter(l => l.event === e.id)
      .map(l => ({ ...e, start: l.from || e.start, end: l.until || e.end, likely: !!l.likely })));
  }

  // Per round: games the player's team plays, and which of those clash with the player's events.
  function playerRounds(team, pid, grid, availability) {
    const evs = eventsFor(pid, availability);
    const out = {};
    for (const [round, games] of Object.entries(team && grid[team] ? grid[team] : {})) {
      const missed = games.filter(m => evs.some(e => within(localDate(m.start), e)));
      out[round] = { games: games.length, available: games.length - missed.length, missed, played: games.filter(m => !missed.includes(m)) };
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

  // Fitted by leave-one-season-out backtest on 1,422 BBL player-seasons, 2013/14 to 2025/26.
  // No BBL games in the window: imports (5+ T20 games elsewhere) and locals, first-timers or returning.
  const PROJ = { mean: 40.1, k: 20, formMean: 45, formK: 40, formW: 3, formC: 2, minForm: 5,
                 fresh: { import: 41, local: 30 }, back: { import: 50, local: 38 } };
  // Half the measured home-minus-away gap of 1.7 SC points per player per game.
  const HOME_EDGE = 0.85;
  const HOME_CITIES = { HEA: ['Brisbane', 'Gold Coast'], HUR: ['Hobart', 'Launceston'], REN: ['Melbourne', 'Geelong'],
                        SCO: ['Perth'], SIX: ['Sydney'], STA: ['Melbourne'], STR: ['Adelaide'], THU: ['Sydney', 'Canberra'] };

  // '2026-12-12' -> '2026/27'
  function seasonOf(day) {
    const y = Number(day.slice(0, 4)) - (Number(day.slice(5, 7)) < 7 ? 1 : 0);
    return `${y}/${String((y + 1) % 100).padStart(2, '0')}`;
  }

  // SC points a game: the two seasons before `current` plus `current` itself, pulled toward the league
  // average, plus T20 form elsewhere (form = [points, games]) that fades as BBL games build up.
  function projection(player, seasons, current, form) {
    const [fsc, fn] = form || [0, 0];
    const formAvg = fn ? fsc / fn : null;
    let sc = 0, g = 0;
    for (const s of [...seasons.filter(x => x < current).slice(-2), current]) {
      const a = player && player.s[s];
      if (a) { sc += a.sc; g += a.m; }
    }
    if (!g) {
      const kind = fn >= PROJ.minForm ? 'import' : 'local';
      const back = !!(player && Object.keys(player.s).length);
      return { avg: (back ? PROJ.back : PROJ.fresh)[kind], g, kind, back, formAvg, fn };
    }
    const base = (sc + PROJ.k * PROJ.mean) / (g + PROJ.k);
    const shrunk = (fsc + PROJ.formK * PROJ.formMean) / (fn + PROJ.formK);
    const lift = PROJ.formW * (shrunk - PROJ.formMean) * PROJ.formC / (g + PROJ.formC);
    return { avg: base + lift, g, raw: sc / g, base, lift, formAvg, fn };
  }

  // SC prices at perPoint dollars per point of last season's league average (median over BBL|16 round-1 players
  // with 7+ games), but blends in a default for 1-3 games, so those prices aren't the rate. Backtest, 992
  // player-seasons with minGames+ games priced at the rate: Proj beat the price (0.77 weight vs 0.18), and a gap
  // of +band or more beat the price 64-79% of the time, -band or less 16-26%.
  const PRICE = { perPoint: 2756, band: 5, minGames: 4 };

  // Proj minus the average the price pays for, labelled on the one-decimal gap the site shows.
  // Only for the tested case: minGames+ SC games last season, recent BBL games.
  function priceGap(p, s) {
    if (!p || !p.g || !s || !s.prev || s.prev[0] < PRICE.minGames || !s.price) return null;
    const implied = s.price / PRICE.perPoint;
    const gap = p.avg - implied;
    const shown = Math.sign(gap) * Number(Math.abs(gap).toFixed(1));
    return { implied, gap, label: shown >= PRICE.band ? 'under' : shown <= -PRICE.band ? 'over' : null };
  }

  // +HOME_EDGE at home, -HOME_EDGE away; nothing at a ground that isn't the home side's.
  function homeEdge(m, team) {
    if (!m.venue || !(HOME_CITIES[m.home] || []).includes(m.venue.city)) return 0;
    return m.home === team ? HOME_EDGE : m.away === team ? -HOME_EDGE : 0;
  }

  // Expected SC points from `games` (fixture matches the player is available for).
  function expected(avg, games, team) {
    return avg == null ? null : games.reduce((s, m) => s + avg + homeEdge(m, team), 0);
  }

  // entries: [{pid, exp: {round: expected points}}] -> best captain options for a round
  function captainPicks(entries, round, n = 3) {
    return entries
      .filter(e => e.exp[round] > 0)
      .map(e => ({ ...e, value: e.exp[round] }))
      .sort((a, b) => b.value - a.value)
      .slice(0, n);
  }

  // Seats players [{pid, pos}] in SC's squad slots. Own positions come first (augmenting paths, so a WKP/BAT
  // can move to free a BAT seat); the FLX seats then take anyone left over.
  function slotFit(players, positions, key = 'squad') {
    const slots = [];
    for (const [pos, r] of Object.entries(positions)) if (pos !== 'FLX') for (let i = 0; i < (r[key] || 0); i++) slots.push({ pos, pid: null });
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
    for (let i = 0; i < ((positions.FLX && positions.FLX[key]) || 0); i++) {
      const p = left.shift();
      slots.push({ pos: 'FLX', pid: p == null ? null : players[p].pid });
    }
    return { slots, unplaced: left.map(i => players[i].pid) };
  }

  // Pool players [{pid, pos, price}] within budget who still leave every squad member a seat.
  function fitting(squad, pool, positions, budget) {
    return pool.filter(p => p.price <= budget && slotFit([...squad, p], positions).unplaced.length === 0);
  }

  // Sets of players that can all be seated form a matroid, so taking the highest value first is optimal.
  function greedySeat(order, positions, key, limit) {
    const chosen = [];
    for (const p of order) {
      if (chosen.length < limit && slotFit([...chosen, p], positions, key).unplaced.length === 0) chosen.push(p);
    }
    return chosen;
  }

  // players [{pid, pos, value}], pins {pid: 'in'|'out'} -> on-field seats, bench, emergencies, captain and vice.
  function bestField(players, positions, emergencies, pins = {}) {
    const byValue = (a, b) => b.value - a.value;
    const size = Object.values(positions).reduce((s, r) => s + (r.active || 0), 0);
    const order = [...players.filter(p => pins[p.pid] === 'in').sort(byValue), ...players.filter(p => !pins[p.pid]).sort(byValue)];
    const field = greedySeat(order, positions, 'active', size);
    const bench = players.filter(p => !field.includes(p)).sort(byValue);
    // One emergency per position, from bench players who have a game.
    const epos = Object.fromEntries(Object.keys(positions).filter(p => p !== 'FLX').map(p => [p, { e: 1 }]));
    const ems = greedySeat(bench.filter(p => p.value > 0), epos, 'e', emergencies);
    const leaders = [...field].sort(byValue).filter(p => p.value > 0);
    return {
      seats: slotFit(field, positions, 'active').slots,
      bench,
      emergencies: slotFit(ems, epos, 'e').slots.filter(s => s.pid),
      captain: leaders[0] ? leaders[0].pid : null,
      vice: leaders[1] ? leaders[1].pid : null,
      unseated: players.filter(p => pins[p.pid] === 'in' && !field.includes(p)).map(p => p.pid),
    };
  }

  // Expected round score: the best `count` on-field values, plus the captain's again.
  function fieldScore(values, count, captainValue) {
    return [...values].sort((a, b) => b - a).slice(0, count).reduce((s, v) => s + v, 0) + (captainValue || 0);
  }

  // The round a change made at `now` counts against: the first league round with a match still to finish.
  function tradeRound(fixture, rounds, now) {
    const open = fixture.filter(m => m.stage === 'league' && Date.parse(m.end) > now)
      .map(m => roundOf(localDate(m.start), rounds)).filter(Boolean);
    return open.length ? Math.min(...open.map(r => r.round)) : null;
  }

  // book {trades: [{round, out, in}], boosts: [round]} -> what's used and left, overall and in `round`.
  // SC has no trades in round 1, then trades_round a round that don't carry over, plus one boost
  // trade in each of up to `boosts` rounds (8 x 3 + 2 = the 26 total).
  function tradeStatus(book, rules, round) {
    const used = book.trades.length;
    const inRound = book.trades.filter(t => t.round === round).length;
    const boosted = book.boosts.includes(round);
    const roundMax = round > 1 ? rules.trades_round + (boosted ? 1 : 0) : 0;
    const roundLeft = Math.max(0, roundMax - inRound);
    const boostsLeft = rules.boosts - book.boosts.length;
    const later = Math.max(0, rules.rounds - round);
    const canBoost = round > 1 && !boosted && boostsLeft > 0;
    return {
      used, inRound, roundMax, boosted, roundLeft, boostsLeft, canBoost,
      left: roundLeft + later * rules.trades_round + Math.min(boostsLeft, later + (canBoost ? 1 : 0)),
    };
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

  // CA is a third party and these numbers are rendered as HTML, so anything that isn't a number becomes 0.
  const num = x => (Number.isFinite(+x) ? +x : 0);

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
          Object.assign(l, { r: num(b.runsScored), bf: num(b.ballsFaced), f4: num(b.foursScored), s6: num(b.sixesScored), out: !!b.isOut,
                             batted: true, batting: !!b.isBatting, bat_pos: b.battingOrder == null ? null : num(b.battingOrder),
                             how: String(b.dismissalText || '') });
        }
        const f = Object.prototype.hasOwnProperty.call(FIELDED, b.dismissalTypeId) && lines.get(b.dismissedByPlayerId);
        if (f) {
          f[FIELDED[b.dismissalTypeId]] += 1;
          if (b.dismissalTypeId === 'RunOut') f.ro_solo += 1;
        }
      }
      for (const w of inn.bowlers || []) {
        const l = lines.get(w.playerId);
        if (!l) continue;
        Object.assign(l, { lb: num(w.totalBallsBowled), rc: num(w.runsConceded), wk: num(w.wicketsTaken),
                           dots: num(w.dotBalls) - num(byes[w.playerId]), mdn: num(w.maidensBowled),
                           wd: num(w.wideBalls), nb: num(w.noBalls), bowling: !!(w.isOnStrike || w.isNonStrike) });
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
    if (Object.prototype.hasOwnProperty.call(idmap, line.ca) && idmap[line.ca]) return idmap[line.ca];
    const t = normName(line.name);
    const hits = squadRows.filter(r => {
      const s = normName(r.n);
      return s[s.length - 1] === t[t.length - 1] && s[0][0] === t[0][0];
    });
    return hits.length === 1 ? hits[0].pid : null;
  }

  // SC userteams/{id}/statsPlayers JSON, or the bookmarklet's "98:true,8:vice", -> [{id, picked, round}].
  function scPicks(x) {
    if (typeof x === 'string') {
      return x.split(',').map(s => /^(\d+):([a-z]+)$/.exec(s)).filter(Boolean).map(m => ({ id: Number(m[1]), picked: m[2] }));
    }
    return ((x && x.players) || []).filter(p => p && p.player_id != null)
      .map(p => ({ id: Number(p.player_id), picked: String(p.picked), round: p.round }));
  }

  // SC marks the on-field 12 as 'true', 'capt' or 'vice' and the bench as 'false'.
  function scImport(picks, idToPid) {
    const squad = [], pins = {}, missing = [];
    let captain = null;
    for (const p of picks) {
      const pid = idToPid[p.id];
      if (!pid) { missing.push(p.id); continue; }
      if (squad.includes(pid)) continue;
      squad.push(pid);
      pins[pid] = ['true', 'capt', 'vice'].includes(p.picked) ? 'in' : 'out';
      if (p.picked === 'capt') captain = pid;
    }
    return { squad, captain, pins, missing };
  }

  return { TEAMS, PROJ, HOME_EDGE, PRICE, localDate, roundOf, teamRounds, eventsFor, playerRounds, overs, seasonLine, seasonOf, projection, priceGap, homeEdge, expected, captainPicks, slotFit, fitting,
           bestField, fieldScore, tradeRound, tradeStatus, sparkPath, venueSplits, playerLog, sumAggs, aggLine, battingText, bowlingText, scPoints, byeDots, caLines, rainRisk, climateRisk, windowHours, matchPid, scPicks, scImport };
});

"""Draws og-image.png (1200x630), the link preview for X, Slack and the like, from the real doubles and byes grid.

Run: python scripts/make_og_image.py
"""
import datetime as dt
import json
import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'og-image.png'
W, H = 1200, 630
NAVY, ACCENT, WHITE, MUTED = (20, 33, 61), (252, 163, 17), (255, 255, 255), (170, 182, 204)
GOOD, BAD, ONE = (47, 133, 90), (197, 48, 48), (44, 62, 100)
TEAMS = ['HEA', 'HUR', 'REN', 'SCO', 'SIX', 'STA', 'STR', 'THU']


def font(size, bold=False):
    for p in ('C:/Windows/Fonts/segoeuib.ttf' if bold else 'C:/Windows/Fonts/segoeui.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def grid():
    fixture = json.loads((ROOT / 'data' / 'fixture.json').read_text(encoding='utf-8'))
    rounds = [r for r in json.loads((ROOT / 'data' / 'rounds.json').read_text(encoding='utf-8'))['rounds'] if not r.get('finals')]
    games = {t: {r['round']: 0 for r in rounds} for t in TEAMS}
    for m in fixture:
        if m['stage'] != 'league':
            continue
        day = (dt.datetime.fromisoformat(m['start'].replace('Z', '+00:00')) + dt.timedelta(hours=11)).date().isoformat()
        r = next((r for r in rounds if r['start'] <= day <= r['end']), None)
        if r:
            for t in (m['home'], m['away']):
                games[t][r['round']] += 1
    return [r['round'] for r in rounds], games


def main():
    img = Image.new('RGB', (W, H), NAVY)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 10], fill=ACCENT)

    d.ellipse([72, 74, 132, 134], fill=ACCENT)
    d.text((150, 62), 'SC BBL Planner', font=font(64, True), fill=WHITE)
    d.text((72, 168), 'For SuperCoach BBL|16', font=font(34), fill=ACCENT)
    lines = ['Doubles, byes and rain risk by round', 'Who misses games for Tests and leagues',
             'Cap check, trade picks and best 12', 'Live SC points and alerts at the toss']
    for i, line in enumerate(lines):
        y = 250 + i * 54
        d.ellipse([76, y + 14, 88, y + 26], fill=ACCENT)
        d.text((106, y), line, font=font(30), fill=WHITE)
    d.text((72, H - 66), 'donkalot.github.io/scbbl', font=font(30, True), fill=WHITE)
    d.text((72 + d.textlength('donkalot.github.io/scbbl', font=font(30, True)) + 20, H - 60),
           'free · unofficial', font=font(24), fill=MUTED)

    rounds, games = grid()
    cell, gap, y0 = 38, 5, 140
    x0 = W - 64 - (62 + len(rounds) * (cell + gap) - gap)
    small, label = font(20, True), font(18)
    gx = x0 + 62
    for j, r in enumerate(rounds):
        t = f'R{r}'
        d.text((gx + j * (cell + gap) + (cell - d.textlength(t, font=label)) / 2, y0 - 30), t, font=label, fill=MUTED)
    for i, team in enumerate(TEAMS):
        y = y0 + i * (cell + gap)
        d.text((x0, y + 8), team, font=small, fill=WHITE)
        for j, r in enumerate(rounds):
            n = games[team][r]
            x = gx + j * (cell + gap)
            d.rounded_rectangle([x, y, x + cell, y + cell], radius=7, fill={0: BAD, 2: GOOD}.get(n, ONE))
            t = str(n)
            d.text((x + (cell - d.textlength(t, font=small)) / 2, y + 7), t, font=small, fill=WHITE)
    ly = y0 + len(TEAMS) * (cell + gap) + 14
    for k, (fill, text) in enumerate([(GOOD, 'double'), (BAD, 'bye')]):
        lx = gx + k * 150
        d.rounded_rectangle([lx, ly, lx + 22, ly + 22], radius=5, fill=fill)
        d.text((lx + 32, ly - 1), text, font=label, fill=MUTED)

    img.save(OUT, 'PNG', optimize=True)
    print(f'Wrote {OUT} ({OUT.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main()

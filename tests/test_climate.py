from pipeline import climate

M = {'id': 1, 'start': '2026-12-12T09:10:00Z', 'end': '2026-12-12T11:40:00Z',
     'venue': {'lat': -37.8, 'lon': 144.9}}


def test_hours_cover_the_window_with_end_of_hour_labels():
    s, e = climate._dt(M['start']), climate._dt(M['end'])
    assert list(climate._hours(s, e)) == ['2026-12-12T10:00', '2026-12-12T11:00', '2026-12-12T12:00']


def test_rates_count_wet_and_heavy_samples_and_skip_gaps():
    rain = {}
    for s, e in climate._samples(M):
        for h in climate._hours(s, e):
            rain[h] = 0.0
    # One year of the 10 is wet on the match date itself, and one sample has a missing hour.
    rain['2025-12-12T11:00'] = 6.0
    rain['2024-12-13T11:00'] = 1.2
    del rain['2023-12-12T10:00']
    assert climate.rates(M, rain) == {'n': 69, 'wet': 2, 'heavy': 1}


def test_unchanged_fixtures_reuse_previous_entries_without_fetching(monkeypatch):
    monkeypatch.setattr(climate, 'hourly', lambda *a: (_ for _ in ()).throw(AssertionError('fetched')))
    prev = {'1': {'k': climate._key(M), 'n': 70, 'wet': 3, 'heavy': 0}}
    assert climate.build([M, {'id': 2, 'venue': None}], prev) == prev

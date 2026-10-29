#!/usr/bin/env python3
"""Self-check for score.py, on real BFCL v4 ground-truth shapes. Run: python3 test_score.py"""
from score import score_task


def task(gt, names=None):
    return {"ground_truth": gt, "names": names or {}}


def call(name, **args):
    return {"name": name, "args": args}


# strings: BFCL normalization; numbers: int == float; optional args ("" or None) may be omitted
t = task([{"uber.ride": {"loc": ["2020 Addison Street, Berkeley, CA, USA"], "type": ["comfort"],
                         "time": [600], "note": ["", None]}}], {"uber_ride": "uber.ride"})
assert score_task(t, [call("uber_ride", loc="2020 addison street berkeley ca usa", type="Comfort", time=600.0)])["pass"]
assert not score_task(t, [call("uber_ride", loc="2020 Addison Street", type="comfort", time=600)])["pass"]
assert not score_task(t, [call("uber_ride", loc="2020 Addison Street, Berkeley, CA, USA", type="comfort")])["pass"]
assert not score_task(t, [call("uber_ride", loc="2020 Addison Street, Berkeley, CA, USA", type="comfort", time=600, x=1)])["pass"]
assert not score_task(t, [call("uber_ride", loc="2020 Addison Street, Berkeley, CA, USA", type="comfort", time="600")])["pass"]

# booleans are not numbers
t = task([{"github_star": {"repos": ["a/b"], "aligned": [True]}}])
assert score_task(t, [call("github_star", repos="a/b", aligned=True)])["pass"]
assert not score_task(t, [call("github_star", repos="a/b", aligned=1)])["pass"]

# parallel: order-free, every expected call once; extra calls fail only "strict"
t = task([{"spotify.play": {"artist": ["Taylor Swift"], "duration": [20]}},
          {"spotify.play": {"artist": ["Maroon 5"], "duration": [15]}}], {"spotify_play": "spotify.play"})
two = [call("spotify_play", artist="Maroon 5", duration=15), call("spotify_play", artist="Taylor Swift", duration=20)]
assert score_task(t, two) == {"pass": True, "strict": True}
assert score_task(t, two + [two[0]]) == {"pass": True, "strict": False}
assert not score_task(t, two[:1])["pass"]
assert not score_task(t, [two[0], two[0]])["pass"]

# a nested dict spec (simple_python_89) and a literal dict (live_multiple_121 ego_info.position)
t = task([{"db_fetch_records": {"conditions": [{"department": ["Science"], "school": ["Bluebird High School", "Bluebird HS"]}]}}])
assert score_task(t, [call("db_fetch_records", conditions={"department": "science", "school": "Bluebird HS"})])["pass"]
assert not score_task(t, [call("db_fetch_records", conditions={"department": "Science"})])["pass"]
t = task([{"get_headway": {"ego_info": [{"position": [{"lateral": 10.5, "longitudinal": 50}], "orientation": [30]}]}}])
assert score_task(t, [call("get_headway", ego_info={"position": {"lateral": 10.5, "longitudinal": 50}, "orientation": 30})])["pass"]

# list values compare element by element
t = task([{"poker_game_winner": {"cards": [{"Alex": [["A of spades", "K of spades"]]}]}}])
assert score_task(t, [call("poker_game_winner", cards={"Alex": ["a of spades", "k of spades"]})])["pass"]
assert not score_task(t, [call("poker_game_winner", cards={"Alex": ["K of spades", "A of spades"]})])["pass"]

print("score.py self-check: all passed")

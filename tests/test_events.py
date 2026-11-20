from datetime import date

import pytest

from edenprairie_news import events

REF = date(2026, 11, 19)
VENUES = ["Staring Lake Outdoor Center", "Staring Lake", "Eden Prairie City Center"]


def run(text, title="Title", ref=REF):
    return events.extract_events(title, text, ref, venues=VENUES)


def test_date_time_and_a_known_venue_in_one_sentence():
    (e,) = run("The open house is Saturday, Nov. 21, from 6 to 8 p.m. at the Staring Lake Outdoor Center.")
    assert (e.start_date, e.start_time, e.end_time) == (date(2026, 11, 21), "18:00", "20:00")
    assert (e.location, e.location_source) == ("Staring Lake Outdoor Center", "venue")  # the longest venue name wins


def test_time_and_place_in_the_following_sentence():
    (e,) = run("The council meeting is Dec. 3. It starts at 7 p.m. at Eden Prairie City Center.")
    assert (e.start_date, e.start_time, e.location) == (date(2026, 12, 3), "19:00", "Eden Prairie City Center")


def test_a_range_of_days_and_ordinal_suffixes():
    (e,) = run("The winter festival runs Dec. 5-7 with free events for families.")
    assert (e.start_date, e.end_date) == (date(2026, 12, 5), date(2026, 12, 7))
    (e2,) = run("The craft sale is on December 12th at 10 a.m.")
    assert (e2.start_date, e2.start_time) == (date(2026, 12, 12), "10:00")


def test_a_street_address_and_a_generic_at_phrase_are_found_when_no_venue_matches():
    (e,) = run("A public hearing is set for Nov. 30 at 6:30 p.m. at 8080 Mitchell Road.")
    assert (e.location, e.location_source) == ("8080 Mitchell Road", "address") and e.start_time == "18:30"
    (e2,) = run("The market opens Nov. 28 at the Community Center.")
    assert (e2.location, e2.location_source) == ("Community Center", "phrase")


def test_unknown_place_stays_empty_instead_of_a_guess():
    (e,) = run("The meeting is Nov. 24 at 7 p.m.")
    assert e.location == "" and e.start_time == "19:00"


def test_dates_in_the_past_and_sentences_that_are_not_events_are_skipped():
    assert run("On Nov. 3 the council voted to approve the budget.") == []  # before the article date
    assert run("The author was born on Dec. 4 in a small town.") == []  # a date but no event wording


def test_year_is_inferred_across_new_year_and_an_explicit_year_wins():
    (e,) = run("The tree lighting is Jan. 5 at the Eden Prairie City Center.", ref=date(2026, 12, 20))
    assert e.start_date == date(2027, 1, 5)
    (e2,) = run("The fair is on Nov. 25, 2027 at the Community Center.")
    assert e2.start_date == date(2027, 11, 25)


def test_abbreviations_do_not_split_a_sentence_and_invalid_dates_are_ignored():
    (e,) = run("Doors open at 6 p.m. Saturday, Nov. 21 for the concert at Staring Lake.")
    assert (e.start_date, e.location) == (date(2026, 11, 21), "Staring Lake")
    assert run("The sale is on Feb. 30 at the Community Center.") == []


def test_the_same_event_mentioned_twice_is_one_candidate():
    assert len(run("The fair is Nov. 28 at 10 a.m. at the Community Center. Again, the fair is Nov. 28 at 10 a.m. at the Community Center.")) == 1


def test_venue_list_loads_longest_first(tmp_path):
    f = tmp_path / "v.yaml"
    f.write_text("venues:\n  - Staring Lake\n  - Staring Lake Outdoor Center\n")
    assert events.load_venues(f) == ["Staring Lake Outdoor Center", "Staring Lake"]
    assert events.load_venues(tmp_path / "missing.yaml") == []


def test_a_date_with_a_clock_time_counts_even_without_event_wording():
    (e,) = run("Author Jane Smith will sign copies of her book at Winding Trail Books on Saturday, Nov. 28 at 2 p.m.")
    assert (e.start_date, e.start_time, e.location) == (date(2026, 11, 28), "14:00", "Winding Trail Books")
    assert run("The new rate takes effect Jan. 1.", ref=date(2026, 12, 20)) == []  # a date, but no event and no time


def test_publish_dates_in_the_feed_formats_are_understood():
    from edenprairie_news.pipeline import reference_date

    assert reference_date("2026-11-18T10:00:00+00:00") == date(2026, 11, 18)
    assert reference_date("Wed, 18 Nov 2026 14:03:00 GMT") == date(2026, 11, 18)
    assert reference_date("not a date") == date.today() and reference_date(None) == date.today()

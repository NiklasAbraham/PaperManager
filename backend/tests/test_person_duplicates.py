"""Rules of services/person_duplicates.py, on names taken from a real library (Oct 2026)."""
from services.person_duplicates import groups


def person(pid, name, degree=1, s2=None):
    return {"id": pid, "name": name, "s2_author_id": s2, "tracked": None, "degree": degree}


def names(people):
    return [[p["name"] for p in g["people"]] for g in groups(people)]


def test_accents_punctuation_and_middle_initials():
    people = [person("1", "Alán Aspuru-Guzik", 5), person("2", "Al'an Aspuru-Guzik"),
              person("3", "Nele P. Quast", 3), person("4", "Nele Quast")]
    assert names(people) == [["Alán Aspuru-Guzik", "Al'an Aspuru-Guzik"], ["Nele P. Quast", "Nele Quast"]]


def test_initials_join_the_only_full_name():
    people = [person("1", "Christian P. Robert", 9), person("2", "C. P. Robert"), person("3", "C. Robert")]
    (g,) = groups(people)
    assert [p["name"] for p in g["people"]] == ["Christian P. Robert", "C. P. Robert", "C. Robert"]
    assert g["reasons"] == ["initials match the only full name"]


def test_initials_left_alone_with_two_candidates_or_a_contradicting_middle_initial():
    two = [person("1", "Christian Robert"), person("2", "Claire Robert"), person("3", "C. Robert")]
    assert names(two) == []
    clash = [person("1", "Christian X. Robert"), person("2", "C. P. Robert")]
    assert names(clash) == []


def test_spelled_out_variants_of_one_name_count_as_one_candidate():
    people = [person("1", "Nele P. Quast", 3), person("2", "Nele Quast"), person("3", "N. Quast")]
    (g,) = groups(people)
    assert len(g["people"]) == 3
    assert g["reasons"] == ["same name without middle initials", "initials match the only full name"]


def test_keeper_has_the_s2_id_then_most_relationships():
    people = [person("1", "Pierre Jacob", 2), person("2", "Pierre E. Jacob", 7), person("3", "Pierre Jacob", 1, s2="123")]
    (g,) = groups(people)
    assert g["people"][0]["id"] == "3"
    assert groups(people, initials=False)[0]["people"][0]["id"] == "3"

from services.note_parser import parse_mentions


def test_basic_mentions():
    result = parse_mentions("Hello @Jan, see #NLP results")
    assert result["people"] == ["Jan"]
    assert result["topics"] == ["NLP"]


def test_no_mentions():
    result = parse_mentions("Just a plain note with no mentions here.")
    assert result["people"] == []
    assert result["topics"] == []


def test_multiple_people():
    result = parse_mentions("Ask @Nele and @Jan about this")
    assert "Nele" in result["people"]
    assert "Jan" in result["people"]


def test_deduplicated():
    result = parse_mentions("@Jan said one thing, @Jan said another")
    assert result["people"].count("Jan") == 1


def test_underscore_name():
    result = parse_mentions("Talk to @Jan_Muller about this")
    assert "Jan Muller" in result["people"]


def test_hyphen_topic():
    result = parse_mentions("See #machine-learning paper")
    assert "machine learning" in result["topics"]


def test_multiple_topics():
    result = parse_mentions("Topics: #NLP and #transformers")
    assert "NLP" in result["topics"]
    assert "transformers" in result["topics"]


def test_mixed():
    result = parse_mentions("@Nele gave me this #arxiv paper on #NLP, cc @Jan")
    assert set(result["people"]) == {"Nele", "Jan"}
    assert "arxiv" in result["topics"]
    assert "NLP" in result["topics"]

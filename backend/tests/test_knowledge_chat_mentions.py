from routers.knowledge_chat import _parse_mentions


def test_parse_mentions_supports_quoted_values_with_spaces_and_colons():
    text = 'Compare @paper:"Attention Is All You Need: A New Era" and @project:"nlp roadmap".'

    mentions = _parse_mentions(text)

    assert mentions == [
        ("paper", "Attention Is All You Need: A New Era"),
        ("project", "nlp roadmap"),
    ]


def test_parse_mentions_keeps_unquoted_mentions_working():
    text = "Use @tag:transformers and @paper:alpha:beta for context"

    mentions = _parse_mentions(text)

    assert mentions == [
        ("tag", "transformers"),
        ("paper", "alpha:beta"),
    ]

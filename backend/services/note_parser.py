import re

# @Name or @First_Last — single token, no spaces, underscore used as word separator
_PERSON_RE = re.compile(r"@([\w][\w\-]*)", re.UNICODE)
# #topic-name or #TopicName (stops at whitespace or punctuation except hyphen)
_TOPIC_RE = re.compile(r"#([\w][\w\-]*)", re.UNICODE)


def parse_mentions(content: str) -> dict:
    """
    Parse @Person and #Topic mentions from markdown text.
    Returns {"people": [...], "topics": [...]} with deduplicated values.
    Underscores in @Name are converted to spaces.
    """
    people = []
    seen_people: set[str] = set()
    for match in _PERSON_RE.finditer(content):
        name = match.group(1).replace("_", " ").strip()
        key = name.lower()
        if key not in seen_people:
            seen_people.add(key)
            people.append(name)

    topics = []
    seen_topics: set[str] = set()
    for match in _TOPIC_RE.finditer(content):
        name = match.group(1).replace("-", " ").replace("_", " ").strip()
        key = name.lower()
        if key not in seen_topics:
            seen_topics.add(key)
            topics.append(name)

    return {"people": people, "topics": topics}

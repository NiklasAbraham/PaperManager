from routers.projects import _list_row


def test_list_row_drops_full_text_and_embedding():
    row = _list_row({"id": "p1", "title": "T", "raw_text": "x" * 10, "embedding": [0.1], "drive_file_id": "d1"})

    assert "raw_text" not in row and "embedding" not in row
    assert row["has_pdf"] is True
    assert row["document_type"] == "paper"


def test_list_row_keeps_document_type_and_flags_missing_pdf():
    row = _list_row({"id": "p2", "title": "N", "document_type": "news_article"})

    assert row["document_type"] == "news_article"
    assert row["has_pdf"] is False

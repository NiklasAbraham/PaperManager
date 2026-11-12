"""Background reference import: id mapping and job bookkeeping."""
from unittest.mock import patch

from services import reference_import as ri


def test_entry_for_maps_arxiv_doi_biorxiv_and_urls():
    assert ri.entry_for("arXiv:2301.01234", None) == {"arxiv": "2301.01234"}
    assert ri.entry_for("10.48550/arXiv.2301.01234v2", None) == {"arxiv": "2301.01234"}
    assert ri.entry_for("2301.01234", None) == {"arxiv": "2301.01234"}
    assert ri.entry_for("10.1101/2023.01.01.522", None) == {"biorxiv": "10.1101/2023.01.01.522"}
    assert ri.entry_for("10.1038/nature14539", None) == {"doi": "10.1038/nature14539"}
    assert ri.entry_for(None, "https://doi.org/10.1038/nature14539") == {"doi": "10.1038/nature14539"}
    assert ri.entry_for(None, "https://arxiv.org/abs/1706.03762") == {"arxiv": "1706.03762"}
    assert ri.entry_for(None, "https://arxiv.org/abs/1706.03762v5") == {"arxiv": "1706.03762"}
    assert ri.entry_for(None, "http://arxiv.org/pdf/1706.03762v2.pdf") == {"arxiv": "1706.03762"}
    assert ri.entry_for(None, "https://www.arxiv.org/abs/2301.01234") == {"arxiv": "2301.01234"}
    assert ri.entry_for(None, "https://example.org/paper.pdf") == {"pdf_url": "https://example.org/paper.pdf"}
    assert ri.entry_for(None, "https://openreview.net/forum?id=abc") is None


def test_start_job_reuses_active_job_for_same_stub():
    ri._jobs.clear()
    with patch.object(ri._executor, "submit") as submit:
        a = ri.start_job(stub_id="s1", source_paper_id="p", doi="10.1/x", url=None, title="T", user_name=None)
        b = ri.start_job(stub_id="s1", source_paper_id="p", doi="10.1/x", url=None, title="T", user_name=None)
    assert a["id"] == b["id"]
    assert submit.call_count == 1
    jobs = ri.list_jobs("p")
    assert [j["id"] for j in jobs] == [a["id"]]
    assert all(not k.startswith("_") for k in jobs[0])
    assert ri.list_jobs("other") == []
    ri._jobs.clear()

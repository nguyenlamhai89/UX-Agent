import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts")))
import check_elevenlabs_docs


def test_check_docs_reports_success_when_contract_markers_exist():
    def fetcher(url):
        doc = next(item for item in check_elevenlabs_docs.DOCS if item["url"] == url)
        return " ".join(doc["markers"])

    result = check_elevenlabs_docs.check_docs(fetcher)
    assert result["status"] == "success"
    assert all(page["status"] == "ok" for page in result["pages"])


def test_check_docs_reports_contract_changes_and_unavailable_pages():
    def fetcher(url):
        if url == check_elevenlabs_docs.DOCS[0]["url"]:
            return "only one marker"
        raise OSError("offline")

    result = check_elevenlabs_docs.check_docs(fetcher)
    assert result["status"] == "warning"
    assert result["pages"][0]["status"] == "contract_changed"
    assert all(page["status"] == "unavailable" for page in result["pages"][1:])

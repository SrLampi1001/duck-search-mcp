"""Tests for the DDG response mapper. Per SPECS §4."""
from duck_search_mcp.ddg import MAPPING_HARD_CAP, map_ddg_response


def test_empty_payload_returns_empty_list():
    assert map_ddg_response({}) == []


def test_abstract_becomes_first_result():
    payload = {
        "Abstract": "...",
        "AbstractText": "Rust is a systems programming language focused on safety.",
        "AbstractURL": "https://en.wikipedia.org/wiki/Rust_(programming_language)",
        "Heading": "Rust (programming language)",
    }
    out = map_ddg_response(payload)
    assert len(out) == 1
    assert out[0]["title"] == "Rust (programming language)"
    assert out[0]["url"].endswith("/Rust_(programming_language)")
    assert "Rust is a systems programming" in out[0]["snippet"]


def test_answer_only_when_no_abstract():
    payload = {"Answer": "42", "AnswerType": "calc", "Heading": "the answer to life"}
    out = map_ddg_response(payload)
    assert len(out) == 1
    assert out[0]["title"] == "the answer to life"
    assert out[0]["snippet"] == "42"
    assert out[0]["url"] == ""


def test_related_topics_split_on_first_dash():
    payload = {
        "RelatedTopics": [
            {"Text": "Rust (programming language) - A multi-paradigm systems language.", "FirstURL": "https://example.com/rust"},
            {"Text": "Cargo - Rust's build tool and package manager.", "FirstURL": "https://example.com/cargo"},
        ]
    }
    out = map_ddg_response(payload)
    assert len(out) == 2
    assert out[0]["title"] == "Rust (programming language)"
    assert "multi-paradigm" in out[0]["snippet"]
    assert out[1]["title"] == "Cargo"
    assert "build tool" in out[1]["snippet"]


def test_related_topics_recurse_into_nested():
    payload = {
        "RelatedTopics": [
            {
                "Topics": [
                    {"Text": "Inner - An inner topic.", "FirstURL": "https://example.com/inner"},
                ]
            },
            {"Text": "Sibling - A sibling topic.", "FirstURL": "https://example.com/sibling"},
        ]
    }
    out = map_ddg_response(payload)
    titles = [r["title"] for r in out]
    assert titles == ["Inner", "Sibling"]


def test_related_topics_hard_cap():
    payload = {
        "RelatedTopics": [
            {"Text": f"Topic {i} - description {i}", "FirstURL": f"https://example.com/{i}"}
            for i in range(50)
        ]
    }
    out = map_ddg_response(payload)
    assert len(out) == MAPPING_HARD_CAP
    assert MAPPING_HARD_CAP == 10


def test_related_topics_without_text_are_dropped():
    payload = {"RelatedTopics": [{"FirstURL": "https://example.com/x"}, {"Text": "OK - has text", "FirstURL": "https://example.com/y"}]}
    out = map_ddg_response(payload)
    assert len(out) == 1
    assert out[0]["title"] == "OK"


def test_image_redirect_definition_meta_are_ignored():
    payload = {
        "Image": "https://example.com/image.png",
        "Redirect": "https://example.com/redirect",
        "Definition": "some def",
        "DefinitionURL": "https://example.com/def",
        "Type": "A",
        "meta": {"x": 1},
        "RelatedTopics": [{"Text": "Only thing - only thing.", "FirstURL": "https://example.com/only"}],
    }
    out = map_ddg_response(payload)
    assert len(out) == 1
    assert out[0]["title"] == "Only thing"


def test_no_dash_in_text_keeps_full_text_as_both_title_and_snippet():
    payload = {"RelatedTopics": [{"Text": "LonelyNoDashHere", "FirstURL": "https://example.com/x"}]}
    out = map_ddg_response(payload)
    # Without a " - " separator there is no clean way to split title and snippet;
    # the mapper uses the whole text for both fields. The SPECS only specifies the
    # " - " split path.
    assert out[0]["title"] == "LonelyNoDashHere"
    assert out[0]["snippet"] == "LonelyNoDashHere"

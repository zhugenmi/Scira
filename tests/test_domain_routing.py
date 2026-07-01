import pytest
from src.mcp.paper_search_mcp.domain_routing import (
    DOMAIN_SOURCES,
    CN_DOMAINS,
    VALID_DOMAINS,
    sources_for_domain,
)


@pytest.mark.parametrize("domain", [
    "computer_science", "biology", "medical", "engineering",
    "social_science", "humanities", "general",
])
def test_all_domains_have_source_lists(domain):
    assert domain in DOMAIN_SOURCES
    assert len(DOMAIN_SOURCES[domain]) > 0


def test_medical_includes_pubmed_not_dblp():
    sources = sources_for_domain(
        "medical", has_chinese=False, wanfang_enabled=False, cnki_enabled=False
    )
    assert "pubmed" in sources
    assert "pmc" in sources
    assert "europepmc" in sources
    assert "dblp" not in sources
    assert "iacr" not in sources
    assert "ssrn" not in sources


def test_cs_includes_dblp_not_pubmed():
    sources = sources_for_domain(
        "computer_science", has_chinese=False, wanfang_enabled=False, cnki_enabled=False
    )
    assert "dblp" in sources
    assert "arxiv" in sources
    assert "pubmed" not in sources


def test_cn_appended_when_chinese_query_and_enabled():
    sources = sources_for_domain(
        "computer_science", has_chinese=True, wanfang_enabled=True, cnki_enabled=True
    )
    assert "wanfang" in sources
    assert "cnki" in sources
    assert sources[-1] == "cnki" or sources[-2] == "wanfang"  # both appended after base


def test_cn_appended_for_cn_domain_even_without_chinese():
    sources = sources_for_domain(
        "medical", has_chinese=False, wanfang_enabled=True, cnki_enabled=True
    )
    assert "wanfang" in sources
    assert "cnki" in sources


def test_cn_not_appended_when_disabled():
    sources = sources_for_domain(
        "medical", has_chinese=True, wanfang_enabled=False, cnki_enabled=False
    )
    assert "wanfang" not in sources
    assert "cnki" not in sources


def test_cn_partial_wanfang_only():
    sources = sources_for_domain(
        "biology", has_chinese=True, wanfang_enabled=True, cnki_enabled=False
    )
    assert "wanfang" in sources
    assert "cnki" not in sources


def test_invalid_domain_falls_back_to_general():
    sources = sources_for_domain(
        "nonexistent", has_chinese=False, wanfang_enabled=False, cnki_enabled=False
    )
    assert sources == DOMAIN_SOURCES["general"]


def test_general_excludes_cn_by_default():
    sources = sources_for_domain(
        "general", has_chinese=False, wanfang_enabled=True, cnki_enabled=True
    )
    assert "wanfang" not in sources  # general + non-Chinese → no CN
    assert "cnki" not in sources


def test_general_with_chinese_adds_cn():
    sources = sources_for_domain(
        "general", has_chinese=True, wanfang_enabled=True, cnki_enabled=True
    )
    assert "wanfang" in sources
    assert "cnki" in sources


def test_no_duplicates_in_output():
    sources = sources_for_domain(
        "medical", has_chinese=True, wanfang_enabled=True, cnki_enabled=True
    )
    assert len(sources) == len(set(sources))


def test_valid_domains_matches_keys():
    assert VALID_DOMAINS == set(DOMAIN_SOURCES.keys())


def test_cn_domains_subset_of_valid():
    assert CN_DOMAINS.issubset(VALID_DOMAINS)

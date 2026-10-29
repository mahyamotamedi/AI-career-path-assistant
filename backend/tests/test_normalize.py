from app.careers.taxonomy import Concept, Taxonomy, get_taxonomy
from app.jobs.normalize import normalize_text, map_skills, map_text_skills, clean_text


def test_persian_and_technical_tokens():
    assert normalize_text("  پايه كاري\n C++ C# .NET sql_basics  ") == "پایه کاری c++ c# .net sql_basics"
    assert normalize_text("كَار ۱۲٣") == "کار 123"
    assert "\u200c" in normalize_text("می‌توانم")


def test_dynamic_mapping_ambiguity_and_order():
    def concept(id, fa, en, aliases):
        return Concept(id=id, label_fa=fa, label_en=en, aliases=aliases)
    tax = Taxonomy(roles={}, concepts={c.id:c for c in [
        concept("excel", "اکسل", "Excel", ["spreadsheet", "مشترک"]),
        concept("cpp", "سی پلاس", "C++", ["مشترک"]),
        concept("csharp", "سی شارپ", "C#", []),
        concept("dotnet", "دات‌نت", ".NET", []),
        concept("power_bi", "پاور بی آی", "Power BI", []),
    ]})
    assert map_skills(["Spreadsheet", "اکسل", "unknown", "C++", "C#", ".NET", "Power BI", "مشترک", "excellent"], tax) == ["excel", "cpp", "csharp", "dotnet", "power_bi"]
    assert map_skills(["دات نت"], tax) == ["dotnet"]


TAX = get_taxonomy()


def test_normalize_text_letters_digits_entities():
    assert normalize_text("پايتون  &amp; كار ۱۲٣") == "پایتون & کار 123"
    assert normalize_text("Power BI") == "power bi"


def test_arabic_letters_map_to_python():
    assert map_skills(["پايتون"], TAX) == ["python_basics"]


def test_excel_english_and_persian():
    assert map_skills(["Excel"], TAX) == ["excel"]
    assert map_skills(["اکسل"], TAX) == ["excel"]


def test_sentence_with_two_skills():
    ids = map_text_skills(["تسلط به SQL و Power BI"], TAX)
    assert ids == ["sql_basics", "bi_tools_basics", "data_visualization"]


def test_unknown_text_returns_empty():
    assert map_skills(["روابط عمومی قوی", "xyzzy"], TAX) == []


def test_clean_text_preserves_display_case_and_zwnj():
    assert clean_text("  ديجي‌كالا &amp; Power BI ۱۲٣\n") == "دیجی‌کالا & Power BI 123"


def test_exact_and_sentence_matching_have_distinct_contracts():
    assert map_skills(["تسلط به SQL و Power BI", "Power BI"], TAX) == []
    assert map_text_skills(["Power BI", "تسلط به SQL و Power BI"], TAX) == [
        "bi_tools_basics", "data_visualization", "sql_basics"
    ]


def test_sentence_matching_uses_boundaries_and_shared_aliases():
    tax = Taxonomy(roles={}, concepts={
        "first": Concept(id="first", label_fa="اول", label_en="First", aliases=["shared", "sql", "go"]),
        "second": Concept(id="second", label_fa="دوم", label_en="Second", aliases=["shared"]),
    })
    assert map_skills(["shared"], tax) == []
    assert map_text_skills(["use shared and SQL", "shared"], tax) == ["first", "second"]
    assert map_text_skills(["unshared sqlish go away"], tax) == []


def test_unknown_sentences_return_empty():
    assert map_text_skills(["روابط عمومی قوی", "xyzzy"], TAX) == []

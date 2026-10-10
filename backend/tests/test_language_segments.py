from app.speech.language_segments import DUTCH, ENGLISH, split_by_language


def test_quoted_dutch_inside_english_explanation():
    text = 'A small correction: Instead of "Ik heb," the correct phrase is "Ik heet," which means "My name is."'
    assert split_by_language(text) == [
        (ENGLISH, "A small correction: Instead of"),
        (DUTCH, '"Ik heb,"'),
        (ENGLISH, "the correct phrase is"),
        (DUTCH, '"Ik heet,"'),
        (ENGLISH, 'which means "My name is."'),
    ]


def test_all_dutch_reply_is_one_dutch_run():
    text = "Goedemorgen! Wat fijn dat je Nederlands wilt leren. Hoe gaat het?"
    assert split_by_language(text) == [(DUTCH, text)]


def test_ambiguous_opener_follows_next_sentence():
    runs = split_by_language("Great! Let's start with a simple greeting.")
    assert runs == [(ENGLISH, "Great! Let's start with a simple greeting.")]


def test_markdown_emphasis_is_not_spoken():
    runs = split_by_language("Say **Hallo, hoe gaat het?** to greet someone.")
    assert runs == [
        (ENGLISH, "Say"),
        (DUTCH, "Hallo, hoe gaat het?"),
        (ENGLISH, "to greet someone."),
    ]


def test_empty_text_has_no_runs():
    assert split_by_language("   ") == []

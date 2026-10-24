import pytest

from krillion.match import Matcher, typo_allowance
from krillion.normalize import key, norm, words

CHEESES = [
    ("cheddar", ["Cheddar"]),
    ("gouda", ["Gouda"]),
    ("edam", ["Edam"]),
    ("gruyere", ["Gruyère", "Gruyere cheese"]),
    ("blue", ["Blue cheese"]),
    ("swiss", ["Swiss", "Swiss cheese"]),
    ("brie", ["Brie"]),
    ("feta", ["Feta"]),
    ("taleggio", ["Taleggio"]),
    ("parmigiano", ["Parmigiano Reggiano", "Parmesan"]),
]
COUNTRIES = [("mali", ["Mali"]), ("malawi", ["Malawi"]), ("bali", ["Bali"])]


@pytest.fixture(scope="module")
def cheese():
    return Matcher(CHEESES)


def test_normalize_strips_accents_filler_and_punctuation():
    assert norm("Gruyère!") == "gruyere"
    assert words("Um, I think it's gouda") == ["gouda"]
    assert key("Blue  Jay") == key("bluejay")


@pytest.mark.parametrize(
    "said,expected",
    [
        ("gouda", "gouda"),
        ("Um I'll say Gouda", "gouda"),
        ("goudas", "gouda"),
        ("blue cheese", "blue"),
        ("parmesan", "parmigiano"),
        ("gruyere cheese", "gruyere"),
    ],
)
def test_exact_and_alias(cheese, said, expected):
    m = cheese.match(said)
    assert m and m.entry_id == expected and m.method == "exact"


def test_transposition_counts_as_one_edit(cheese):
    m = cheese.match("gouad")
    assert m and m.entry_id == "gouda" and m.method == "typo" and m.distance == 1


def test_allowance_scales_with_length(cheese):
    m = cheese.match("talegio cheese")  # 8 letters: one edit allowed
    assert m and m.entry_id == "taleggio" and m.distance == 1
    m = cheese.match("parmigano regiano")  # 18 letters: two edits allowed
    assert m and m.entry_id == "parmigiano" and m.method == "typo" and m.distance == 2
    m = cheese.match("parmijano regiano")  # three edits: too far to spell, but sounds the same
    assert m and m.entry_id == "parmigiano" and m.method == "sound"


def test_short_names_get_no_typo_allowance(cheese):
    assert typo_allowance(4) == 0
    m = cheese.match("bree")
    # Not a typo match; it may still be caught as a sound-alike of brie.
    assert m is None or (m.entry_id == "brie" and m.method == "sound")


def test_short_sound_codes_need_close_spelling(cheese):
    # pule (a real cheese missing from this list) and blue share the code "PL"
    assert cheese.match("pule") is None


def test_sound_alike_catches_mishearing(cheese):
    m = cheese.match("grew air")
    assert m and m.entry_id == "gruyere" and m.method == "sound"


def test_close_entries_stay_distinct():
    m = Matcher(COUNTRIES)
    assert m.match("mali").entry_id == "mali"
    assert m.match("bali").entry_id == "bali"
    assert m.match("malawi").entry_id == "malawi"


def test_tie_between_two_entries_is_not_guessed():
    m = Matcher([("carol", ["Carol"]), ("coral", ["Coral"])])
    assert m.match("corol") is None  # one edit from both, same sound as both


def test_recognizer_alternatives_are_tried_in_order(cheese):
    m = cheese.match(["cheddar", "gouda"])
    assert m.entry_id == "cheddar"
    m = cheese.match(["xyzzy", "gouda"])
    assert m.entry_id == "gouda"


def test_unrelated_words_do_not_match(cheese):
    assert cheese.match("bicycle") is None
    assert cheese.match("") is None


def test_shared_category_words_do_not_earn_typo_allowance():
    cakes = [("joffre", ["Joffre cake"]), ("carrot", ["Carrot cake"]), ("lemon", ["Lemon cake"]),
             ("pound", ["Pound cake"]), ("sponge", ["Sponge cake"])]
    m = Matcher(cakes)
    assert m.match("coffee cake") is None  # coffee vs joffre: two edits on a 6-letter word
    m2 = Matcher(cakes + [("kyiv", ["Kyiv cake"])])
    assert m2.match("coffee cake") is None  # coffee and kyiv share a sound code, not a spelling
    assert m.match("carot cake").entry_id == "carrot"
    assert m.match("carrot").entry_id == "carrot"


def test_best_guess_wins_over_a_weaker_guess():
    m = Matcher([("pyr", ["Great Pyrenees"]), ("pwd", ["Portuguese Water Dog", "Portie"]),
                 ("shep", ["Pyrenean Shepherd"])])
    assert m.match(["Pyrenees", "porties"]).entry_id == "pyr"  # partial on the best guess
    assert m.match(["Pyrenees", "porties"]).method == "partial"
    assert m.match(["zzz", "porties"]).entry_id == "pwd"  # a lower guess may still match exactly


def test_words_in_several_names_go_to_the_judge():
    m = Matcher([("pwd", ["Portuguese Water Dog"]), ("swd", ["Spanish Water Dog"]), ("mast", ["Mastiff"]),
                 ("lab", ["Labrador Retriever"]), ("gold", ["Golden Retriever"])])
    assert m.match(["water dog"]) is None
    assert set(m.candidates("water dog")) == {"pwd", "swd"}

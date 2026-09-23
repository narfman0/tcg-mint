"""What `mint fonts` and `mint doctor` report about the faces in fonts/."""
from mint import fonts


def put(d, *names):
    for n in names:
        (d / n).write_bytes(b"")
    return d


def test_report_is_per_face_not_per_family(tmp_path):
    """The roman alone is not enough. The frame sets flavor and reminder text in italic, and a
    family matched without an italic face is sheared into a fake one rather than falling back."""
    have, missing = fonts.report(put(tmp_path, "Beleren-Bold.ttf", "Matrix-Bold.ttf", "Mplantin.ttf"))
    assert ("MPlantin", 400, "italic") in missing
    assert "MPlantin" in have  # the family is there; the face is not
    assert [m for m in missing if m[0] != "MPlantin"] == []


def test_report_is_satisfied_by_the_full_set(tmp_path):
    have, missing = fonts.report(put(tmp_path, "Beleren-Bold.ttf", "Matrix-Bold.ttf",
                                     "Mplantin.ttf", "Mplantin-Italic.ttf"))
    assert missing == []
    assert set(have["MPlantin"]) == {(400, "normal"), (400, "italic")}


def test_report_misses_a_family_that_is_wholly_absent(tmp_path):
    _, missing = fonts.report(put(tmp_path, "Mplantin.ttf", "Mplantin-Italic.ttf"))
    assert ("Beleren", 700, "normal") in missing and ("Matrix Bold", 700, "normal") in missing


def test_shown_names_each_face(tmp_path):
    have, _ = fonts.report(put(tmp_path, "Mplantin.ttf", "Mplantin-Italic.ttf"))
    assert fonts.shown(have["MPlantin"]) == "Mplantin.ttf (roman), Mplantin-Italic.ttf (italic)"

"""Unit tests for content_quality — pure function and DB helper."""

from app.ingest.content_quality import is_usable_extracted_text


class TestIsUsableExtractedText:
    def test_good_page_passes(self) -> None:
        text = (
            "Wilfrid Laurier University offers a Bachelor of Business Administration "
            "program with concentrations in accounting, finance, and marketing. "
            "Students complete 40 credits over four years, including core requirements "
            "and elective courses. The program is accredited by AACSB. "
            "Admission requirements include a minimum 75% average in six Grade 12 "
            "U/M courses including English and two other specified subjects. "
            "Students are encouraged to apply through OUAC by the February 1 deadline."
        )
        assert is_usable_extracted_text(text)

    def test_empty_string_rejected(self) -> None:
        assert not is_usable_extracted_text("")

    def test_whitespace_only_rejected(self) -> None:
        assert not is_usable_extracted_text("   \n\t  ")

    def test_too_short_rejected(self) -> None:
        # Very short snippet — under MIN_DOCUMENT_TOKENS
        assert not is_usable_extracted_text("Hello world.")

    def test_navigation_shell_rejected(self) -> None:
        # ~40 words of navigation text — under token threshold
        text = " ".join(["Home", "Academics", "Students", "Alumni"] * 8)
        assert not is_usable_extracted_text(text)

    def test_onetrust_boilerplate_rejected(self) -> None:
        long_prefix = "word " * 200  # push past token threshold
        text = long_prefix + "By selecting Accept All, you consent to our use of cookies."
        assert not is_usable_extracted_text(text)

    def test_cookie_consent_rejected(self) -> None:
        long_prefix = "word " * 200
        text = long_prefix + "We use cookies to provide you with the best experience."
        assert not is_usable_extracted_text(text)

    def test_privacy_preference_center_rejected(self) -> None:
        long_prefix = "word " * 200
        text = long_prefix + "Privacy Preference Center — manage your cookie settings."
        assert not is_usable_extracted_text(text)

    def test_strictly_necessary_cookies_rejected(self) -> None:
        long_prefix = "word " * 200
        text = long_prefix + "Strictly necessary cookies cannot be disabled."
        assert not is_usable_extracted_text(text)

    def test_none_rejected(self) -> None:
        # Defensive: callers should pass str but guard anyway
        assert not is_usable_extracted_text(None)  # type: ignore[arg-type]

    def test_academic_calendar_page_passes(self) -> None:
        text = (
            "Business Administration (BBA) — Accounting Concentration. "
            "To be eligible for graduation, a student must complete a minimum of 40 credits. "
            "Year 1: BU111 (0.5), BU121 (0.5), EC120 (0.5), EC140 (0.5), MA101 (0.5). "
            "Year 2: BU231 (0.5), BU283 (0.5), BU288 (0.5), BU398 (0.5). "
            "Electives: students choose four 0.5-credit electives from the approved list. "
            "Prerequisite: BU283 requires a minimum grade of 60% in EC120. "
            "Students must maintain a minimum cumulative GPA of 5.0 (C) to remain in good standing. "
            "The concentration requires BU387, BU387, BU481, and BU482 as required core courses."
        )
        assert is_usable_extracted_text(text)

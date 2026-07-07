import streamlit as st
from deep_translator import GoogleTranslator
from langdetect import detect, LangDetectException
from nltk.tokenize import wordpunct_tokenize, TreebankWordDetokenizer
from spellchecker import SpellChecker

# Minimum number of characters required before we bother processing input.
# Prevents wasted API calls / language-detection errors on near-empty strings.
MIN_INPUT_LENGTH = 3

# ISO language codes supported by pyspellchecker.
# Only languages in this set are eligible for the spellcheck feature.
SPELL_LANGS = {"en", "es", "fr", "pt", "de", "ru", "ar", "eu", "lv", "nl"}

# Display name (Vietnamese) -> ISO/Google Translate language code.
# Used to populate the "translate to" dropdown and to look up codes.
TARGET_LANGS = {
    "Tiếng Việt": "vi",
    "Tiếng Anh": "en",
    "Tiếng Pháp": "fr",
    "Tiếng Nhật": "ja",
    "Tiếng Trung (Giản thể)": "zh-CN",
    "Tiếng Hàn": "ko",
    "Tiếng Đức": "de",
}

# Sample sentences shown in the "Ví dụ" (Examples) expander on the Translation tab.
EXAMPLES_T = [
    "Xin chào, bạn khỏe không?",
    "I would like to book a table for two.",
    "Bonjour, comment ça va ?",
]

# Sample sentences (with intentional typos) shown on the Spellcheck tab.
EXAMPLES_S = [
    "Ths is a smple sentnce with typos.",
    "I recieve your mesage yesterday.",
    "Ella tien un problma con su compañero.",
]


# ---------- Core logic ----------

@st.cache_resource(show_spinner=False)
def get_spellchecker(code):
    """
    Build (and cache) a SpellChecker instance for a given language code.
    Cached via st.cache_resource so we don't reload the dictionary from disk
    on every rerun/interaction — SpellChecker objects are expensive to create.
    """
    return SpellChecker(language=code)


def language_name(code):
    """
    Convert an ISO language code (e.g. 'en', 'zh-cn') into its Vietnamese
    display name from TARGET_LANGS (e.g. 'Tiếng Anh').
    Falls back to returning the raw code if it's not one of our 7 target
    languages (langdetect can return many more codes than TARGET_LANGS covers).
    Comparison is case-insensitive because langdetect returns lowercase codes
    (e.g. 'zh-cn') while TARGET_LANGS stores 'zh-CN'.
    """
    for name, lang_code in TARGET_LANGS.items():
        if lang_code.lower() == code.lower():
            return name
    return code


def detect_language(raw):
    """
    Detect the language of a string using langdetect.
    Returns an ISO code (e.g. 'en', 'vi') or None if detection fails
    (e.g. input is too short, ambiguous, or gibberish).
    """
    try:
        return detect(raw)
    except LangDetectException:
        return None


def fix_typos(text, code):
    """
    Run spell-correction over `text` using a SpellChecker for language `code`.

    Steps:
      1. Tokenize the text into words/punctuation (wordpunct_tokenize keeps
         punctuation as separate tokens so it isn't "corrected").
      2. For each alphabetic token longer than 1 char, ask SpellChecker for
         its best correction (falls back to the original token if no
         suggestion is found).
      3. Re-apply the original capitalization style (Title Case / ALL CAPS)
         to the corrected word, so "HELLO" -> "HELLO" not "hello".
      4. Reassemble the tokens back into a natural-looking sentence.

    Returns:
      (fixed_text, changed) where `changed` is True if any token differs
      from the original — used to tell the user whether typos were found.
    """
    spell = get_spellchecker(code)
    tokens = wordpunct_tokenize(text)
    fixed = []

    for token in tokens:
        # Only attempt correction on real words (skip numbers, punctuation,
        # single letters like "I" or "a" which are usually already correct).
        if token.isalpha() and len(token) > 1:
            suggestion = spell.correction(token.lower()) or token
            # Preserve original casing style on the corrected word.
            suggestion = suggestion.title() if token.istitle() else suggestion
            suggestion = suggestion.upper() if token.isupper() else suggestion
            fixed.append(suggestion)
        else:
            fixed.append(token)  # leave punctuation/numbers untouched

    # Detokenize turns the list of tokens back into a proper sentence string
    # (handles spacing around punctuation correctly).
    return TreebankWordDetokenizer().detokenize(fixed), fixed != tokens


def run_spellcheck(text):
    """
    Full spellcheck pipeline for the UI: validate input -> detect language ->
    check that language is supported -> run correction.
    Returns a result dict with "ok": True/False so the UI can branch on it
    without needing try/except.
    """
    raw = text.strip()

    # Guard against empty/near-empty input before wasting a detect() call.
    if len(raw) < MIN_INPUT_LENGTH:
        return {"ok": False, "error": f"Nhập tối thiểu {MIN_INPUT_LENGTH} ký tự."}

    code = detect_language(raw)

    if code is None:
        return {"ok": False, "error": "Không nhận diện được ngôn ngữ."}

    # pyspellchecker only ships dictionaries for a limited set of languages.
    if code not in SPELL_LANGS:
        return {
            "ok": False,
            "error": f"pyspellchecker chưa hỗ trợ {language_name(code)} ({code}).",
        }

    fixed, changed = fix_typos(raw, code)

    return {
        "ok": True,
        "language": language_name(code),
        "fixed": fixed,
        "changed": changed,
    }


def run_translation(text, target_code):
    """
    Full translation pipeline for the UI: validate input -> detect source
    language -> skip translation if source == target -> call Google
    Translate via deep_translator -> return a result dict.
    """
    raw = text.strip()

    if len(raw) < MIN_INPUT_LENGTH:
        return {"ok": False, "error": f"Nhập tối thiểu {MIN_INPUT_LENGTH} ký tự"}

    source = detect_language(raw)

    if source is None:
        return {"ok": False, "error": "Không nhận diện được ngôn ngữ"}

    # Case-insensitive compare: langdetect returns lowercase ('zh-cn') while
    # TARGET_LANGS stores 'zh-CN'. Without .lower() this shortcut would never
    # trigger for Chinese even when source and target are effectively equal.
    if source.lower() == target_code.lower():
        return {
            "ok": True,
            "source": language_name(source),
            "target": language_name(target_code),
            "translated": raw,
            "note": "Câu đã ở ngôn ngữ đích, không cần dịch",
        }

    try:
        # deep_translator calls Google Translate's web endpoint under the hood;
        # this requires internet access and can raise on network/API errors.
        translated = GoogleTranslator(source=source, target=target_code).translate(raw)
    except Exception as e:
        return {"ok": False, "error": f"Lỗi dịch: {e}"}

    return {
        "ok": True,
        "source": language_name(source),
        "target": language_name(target_code),
        "translated": translated,
    }


# ---------- UI ----------

# Basic page setup — must be the first Streamlit command executed.
st.set_page_config(
    page_title="NLP Pipeline Demo",
    layout="centered",
)

st.title("Streamlit NLP Pipeline Demo")
st.caption("Hai ứng dụng: Dịch văn bản · Sửa lỗi chính tả")

# Two independent feature tabs, sharing the same page.
tab_t, tab_s = st.tabs(["Dịch văn bản", "Sửa lỗi chính tả"])

# ===== Tab 1: Translation =====
with tab_t:
    # Initialize session_state key once so results persist across reruns
    # (Streamlit reruns the whole script on every widget interaction).
    st.session_state.setdefault("res_t", None)

    with st.expander("Ví dụ"):
        for ex in EXAMPLES_T:
            st.markdown(f"- {ex}")

    # st.form batches the text area + dropdown so nothing runs until the
    # user explicitly clicks "Dịch" (avoids re-translating on every keystroke).
    with st.form("form_translate"):
        text_t = st.text_area("Câu cần dịch", height=90)

        target = st.selectbox("Dịch sang", list(TARGET_LANGS.keys()))

        submitted_t = st.form_submit_button("Dịch", type="primary")

    # Only run translation logic when the form was actually submitted.
    if submitted_t:
        st.session_state["res_t"] = run_translation(text_t, TARGET_LANGS[target])

    res_t = st.session_state["res_t"]

    # Render the last result (persists even after the form resets on rerun).
    if res_t is not None:
        if res_t["ok"]:
            st.success(f"Từ **{res_t['source']}** → **{res_t['target']}**")
            st.write(res_t["translated"])
            if "note" in res_t:
                st.info(res_t["note"])
        else:
            st.error(res_t["error"])

# ===== Tab 2: Spellcheck =====
with tab_s:
    st.session_state.setdefault("res_s", None)

    with st.expander("Ví dụ"):
        for ex in EXAMPLES_S:
            st.markdown(f"- {ex}")

    with st.form("form_spellcheck"):
        text_s = st.text_area("Câu cần kiểm tra chính tả", height=90)

        submitted_s = st.form_submit_button("Kiểm tra", type="primary")

    if submitted_s:
        st.session_state["res_s"] = run_spellcheck(text_s)

    res_s = st.session_state["res_s"]

    if res_s is not None:
        if res_s["ok"]:
            st.success(f"Ngôn ngữ nhận diện: **{res_s['language']}**")
            st.write(res_s["fixed"])
            if not res_s["changed"]:
                st.info("Không tìm thấy lỗi chính tả nào.")
        else:
            st.error(res_s["error"])

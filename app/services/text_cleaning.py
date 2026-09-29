"""Light, safe clean-up of text extracted from government PDFs (P3/P4).

Many Hindi/Marathi PDFs are printed with "fake bold" (every glyph drawn twice), so the text layer
repeats vowel signs: "महाारााष्ट्र" for "महाराष्ट्र", "शेेतकरीी" for "शेतकरी". Real Devanagari
never has the same dependent sign twice in a row, so collapsing repeats is lossless for
correct text. Wrong glyph-to-Unicode mappings ("भारि" for "भारत") cannot be undone here.
"""

import re
import unicodedata

# The same dependent vowel sign / anusvara / candrabindu / visarga / nukta repeated
_REPEATED_SIGN = re.compile("([\u0901-\u0903\u093c\u093e-\u094c])\\1+")


def clean_extracted_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\ufffd", "")
    return _REPEATED_SIGN.sub(r"\1", text)

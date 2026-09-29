"""Unicode-aware tokenizer for sparse retrieval (BM25) over English, Hindi and Marathi (P8).

sklearn's default token_pattern r"(?u)\\b\\w\\w+\\b" breaks Devanagari words: Python's \\w does not
match combining marks such as the matras ा ि ी ु and the halant ्, so "प्रधानमंत्री" is cut into
pieces and short words like "बीमा" vanish. Here a word is a run of letters, digits and marks
(the whole Devanagari block except the danda punctuation), so Hindi/Marathi words stay whole.

Normalisation: Unicode NFC, zero-width joiners removed, Devanagari digits -> ASCII digits
(so "६,०००" and "6,000" match), case-folded. Punctuation (including । and ॥) separates tokens.
"""

import re
import unicodedata

# Letters/digits (\w without "_") plus Devanagari U+0900-097F except danda/double danda
# (U+0964/0965) and generic combining marks U+0300-036F
_TOKEN = re.compile(r"[\w\u0900-\u0963\u0966-\u097f\u0300-\u036f]+")
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"))

# Small hand-written stopword lists: only very frequent function words, so content words
# (scheme names, amounts, eligibility terms) are never dropped.
ENGLISH_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "at", "by", "for", "from",
    "with", "as", "is", "are", "was", "were", "be", "been", "being", "am", "it", "its", "this",
    "that", "these", "those", "which", "who", "whom", "what", "there", "their", "they", "them",
    "he", "she", "his", "her", "we", "our", "you", "your", "i", "me", "my", "do", "does", "did",
    "has", "have", "had", "will", "would", "shall", "should", "can", "could", "may", "might",
    "not", "no", "so", "than", "then", "such", "into", "about", "also", "any", "each", "other",
}
HINDI_STOPWORDS = {
    "का", "की", "के", "को", "में", "से", "पर", "है", "हैं", "था", "थी", "थे", "हो", "होता", "होती",
    "होते", "और", "या", "भी", "तो", "ही", "यह", "वह", "ये", "वे", "इस", "उस", "इन", "उन", "इसके",
    "उसके", "एक", "कि", "जो", "जिस", "जिन", "तक", "द्वारा", "लिए", "साथ", "कर", "करना", "करने",
    "किया", "गया", "गई", "गए", "रहा", "रही", "रहे", "जा", "जाता", "जाती", "जाते", "ने", "नहीं",
    "क्या", "कैसे", "कौन",
}
MARATHI_STOPWORDS = {
    "आहे", "आहेत", "होते", "होता", "होती", "आणि", "व", "किंवा", "या", "ही", "हा", "हे", "ते", "तो",
    "ती", "त्या", "त्याच्या", "त्यांच्या", "त्यांना", "यांच्या", "यांना", "मध्ये", "साठी", "ला",
    "ना", "चा", "ची", "चे", "च्या", "ने", "नी", "वर", "पर्यंत", "येथे", "तसेच", "म्हणून", "करून",
    "केले", "केली", "करण्यात", "येते", "येईल", "आले", "नाही", "काय", "कसे", "कोणती", "कोणते",
    "एक", "तर", "पण", "जे", "जी", "जो",
}
STOPWORDS = ENGLISH_STOPWORDS | HINDI_STOPWORDS | MARATHI_STOPWORDS


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    return text.translate(_DEVANAGARI_DIGITS).replace("_", " ").casefold()


def tokenize(text: str, remove_stopwords: bool = True) -> list[str]:
    tokens = _TOKEN.findall(normalize(text))
    if remove_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS]
    return tokens

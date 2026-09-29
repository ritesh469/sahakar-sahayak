"""Rule-based language detection for questions: en | hi | mr | hinglish.

Used to tell the answer model which language/script to reply in (LLMs tend to answer
Hinglish questions in Devanagari Hindi) and for language-wise evaluation.
"""

import re

LANG_NAMES = {
    "en": "English",
    "hi": "Hindi (Devanagari script)",
    "mr": "Marathi (Devanagari script)",
    "hinglish": "Hinglish (Hindi words written in Latin letters, NOT Devanagari)",
}

# Frequent function / question words that separate Hindi from Marathi
_HINDI_WORDS = {
    "है", "हैं", "क्या", "कौन", "कौनसी", "कितना", "कितनी", "कितने", "कैसे", "कब", "कहाँ", "में",
    "का", "की", "के", "को", "से", "और", "लिए", "मिलता", "मिलती", "होता", "होती", "किसे", "नहीं",
}
_MARATHI_WORDS = {
    "आहे", "आहेत", "काय", "कोणती", "कोणते", "कोणता", "किती", "कसे", "कशी", "कसा", "केव्हा", "कुठे",
    "आणि", "मध्ये", "साठी", "मिळते", "मिळतो", "मिळतात", "करावा", "करावे", "नाही", "यांना", "ला",
}
# Romanised Hindi words that are rare in English text
_HINGLISH_WORDS = {
    "hai", "hain", "kya", "kaun", "kaunsi", "kitna", "kitni", "kitne", "kaise", "kab", "kahan",
    "mein", "me", "ka", "ki", "ke", "ko", "se", "aur", "liye", "milta", "milti", "milte", "hota",
    "hoti", "hote", "nahi", "nahin", "kaha", "batao", "bataiye", "chahiye", "sakta", "sakte",
    "wale", "wala", "yojana", "sarkar", "kisan", "kisko", "kiske", "paisa", "paise", "karna",
    "karein", "karu", "raha", "rahi", "gaya", "tak", "bhi", "koi", "kuch", "jaankari", "sahkari",
}

_WORD = re.compile(r"[\w\u0900-\u097f]+")


def _is_devanagari(ch: str) -> bool:
    return "\u0900" <= ch <= "\u097f"


def detect_language(text: str) -> str:
    letters = [c for c in text if c.isalpha() or _is_devanagari(c)]
    if not letters:
        return "en"
    dev_ratio = sum(1 for c in letters if _is_devanagari(c)) / len(letters)
    words = [w.lower() for w in _WORD.findall(text)]

    if dev_ratio >= 0.5:
        hi = sum(w in _HINDI_WORDS for w in words)
        mr = sum(w in _MARATHI_WORDS for w in words) + text.count("ळ")
        # Marathi case endings glued to nouns: शेतकऱ्यांना, योजनेचा, कर्जाची
        mr += sum(1 for w in words if w.endswith(("ांना", "ाचा", "ाची", "ाचे", "ेचा", "ेची", "ेचे")))
        return "mr" if mr > hi else "hi"

    hinglish_hits = sum(w in _HINGLISH_WORDS for w in words)
    # "ki", "ke", "me", "se" also appear in English, so require two hits (or a third of the words)
    if hinglish_hits >= 2 or (words and hinglish_hits / len(words) >= 0.34):
        return "hinglish"
    return "en"

"""Prompt-injection patterns for user text, in English, Hindi, Hinglish and Marathi (P9).

One list, used by the request validators in app/models.py (layer 0, before llm-guard). The
patterns target instruction-override phrasing, not single words: "ignore previous audit
objections" or "pichle saal ke niyam" are normal questions and must pass, so every pattern
needs an instruction/prompt/rules object or a role-change frame.

Matching runs on normalized text (see normalize()): NFC, zero-width characters and the
nukta removed (so "नज़रअंदाज़" and "नजरअंदाज" match alike, and a zero-width joiner cannot split
a keyword), case-folded, whitespace collapsed. Patterns are therefore written lowercase and
without nukta.
"""

from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿़"))  # + nukta

# End of a Devanagari word: Python's \b does not work there (matras are not \w)
_END = r"(?=[\s।?!.,;:]|$)"

# Objects that make "ignore/forget X" an attack: instructions, prompt, rules...
_EN_OBJ = r"(?:instructions?|rules|prompts?|directions|guidelines|messages?|context)"
_HI_OBJ = r"(?:निर्देश|निर्देशों|नियम|नियमों|आदेश|आदेशों|इंस्ट्रक्शन|इंस्ट्रक्शंस|प्रॉम्प्ट|प्रोम्प्ट)"
_HING_OBJ = r"(?:instructions?|nirdesh|nirdeshon|rules|niyam|niyamon|prompts?|baatein|baaton)"
_MR_OBJ = r"(?:सूचना|सूचनांना|निर्देश|नियम|नियमांना|आदेश|प्रॉम्प्ट)"

# (name, language, regex). Order does not matter; the first match is reported.
INJECTION_PATTERNS: list[tuple[str, str, str]] = [
    # ---- English ----
    ("ignore_instructions", "en",
     rf"\b(?:ignore|disregard|forget|override|bypass)\s+(?:(?:all|any|the|your|my|these|those|of)\s+)*"
     rf"(?:previous|prior|above|earlier|preceding|system|original|initial)\s+{_EN_OBJ}\b"),
    ("ignore_instructions", "en",
     r"\b(?:ignore|disregard|forget)\s+(?:(?:all|any|the|your)\s+)*(?:instructions?|prompts?|directions)\b"),
    ("reveal_prompt", "en",
     r"\b(?:reveal|show|print|repeat|display|output|leak|tell\s+me|give\s+me)\b[^.?!]{0,30}?"
     r"\b(?:system\s*prompt|your\s+(?:instructions|prompt|rules|guidelines)|hidden\s+(?:instructions|prompt))"),
    ("role_change", "en",
     r"\byou\s+are\s+(?:now|no\s+longer)\s+(?:a|an|my|the|dan|free|unrestricted|not)\b"),
    ("role_change", "en", r"\b(?:pretend|roleplay|role-play)\s+(?:to\s+be|as|you)\b"),
    ("role_change", "en", r"\bfrom\s+now\s+on,?\s+(?:you|act|behave|respond)\b"),
    ("new_instructions", "en", r"\bnew\s+instructions?\s*:|\boverride\s+(?:previous|prior|your|all|the\s+system)\b"),
    ("jailbreak", "en", r"\b(?:developer|dan|god)\s+mode\b|\bjailbreak"),
    ("script_injection", "en", r"<\s*script|javascript:|\bon(?:load|error|click|mouseover|focus|submit)\s*="),

    # ---- Hinglish (Hindi in Latin letters) ----
    ("ignore_instructions", "hinglish",
     rf"\b(?:pichh?l[aei]|purane|upar\s+wal[ae]|sabhi|saare|sare|sab)\s+{_HING_OBJ}\s+(?:ko\s+)?"
     r"(?:bh[uo]o?l|ignore|nazarandaz|chh?od)"),
    ("ignore_instructions", "hinglish",
     rf"\b{_HING_OBJ}\s+(?:ko\s+)?(?:bh[uo]o?l\s*(?:jao|ja|jaiye|do)|ignore\s+(?:karo|kar\s*do|kijiye|karke))\b"),
    ("reveal_prompt", "hinglish",
     r"\b(?:system\s*prompt|(?:apn[ae]|tumhar[ae]|aapk[ae]|ter[ae]|hidden|andar\s+ke|secret)\s+"
     r"(?:prompt|instructions?|nirdesh|rules))\s+(?:ko\s+)?"
     r"(?:dikhao|dikha\s*do|dikhaiye|batao|bata\s*do|bataiye|print\s+karo|reveal\s+karo|share\s+karo|likho)\b"),
    ("role_change", "hinglish",
     r"\b(?:ab\s+(?:se\s+)?(?:tum|tu)|(?:tum|tu)\s+ab)\s+(?:ek\s+)?\w+(?:\s+\w+){0,2}\s+(?:ho|bano|ban\s+jao)\b"),
    ("role_change", "hinglish", r"\bab\s+(?:se\s+)?aap\s+ek\s+\w+(?:\s+\w+)?\s+(?:hain|ho|baniye)\b"),
    ("role_change", "hinglish", r"\b\w+\s+(?:ki\s+tarah|jaisa|jaise)\s+(?:act|behave)\s+karo\b"),

    # ---- Hindi (Devanagari) ----
    ("ignore_instructions", "hi",
     rf"(?:पिछले|पिछली|पहले\s+के|ऊपर\s+के|सभी|सारे|पुराने)\s+(?:सभी\s+)?{_HI_OBJ}\s*(?:को\s+)?"
     r"(?:भूल|भुला|अनदेखा|नजरअंदाज|इग्नोर|छोड़)"),
    ("ignore_instructions", "hi", rf"{_HI_OBJ}\s+को\s+(?:भूल|भुला|अनदेखा|नजरअंदाज|इग्नोर)"),
    ("reveal_prompt", "hi",
     r"(?:सिस्टम\s*प्रॉम्प्ट|सिस्टम\s*प्रोम्प्ट|(?:अपने|अपना|तुम्हारे|आपके|छिपे\s+(?:हुए\s+)?|आंतरिक)\s*"
     r"(?:निर्देश|प्रॉम्प्ट|प्रोम्प्ट|नियम))\s*(?:को\s+)?"
     r"(?:दिखाओ|दिखाइए|दिखा\s+दो|बताओ|बताइए|बता\s+दो|प्रिंट|लिखो|साझा)"),
    ("role_change", "hi",
     rf"(?:अब\s+(?:से\s+)?(?:तुम|तू)|(?:तुम|तू)\s+अब)\s+(?:एक\s+)?\S+(?:\s+\S+){{0,2}}\s+(?:हो|बनो|बन\s+जाओ){_END}"),
    ("role_change", "hi", rf"अब\s+(?:से\s+)?आप\s+एक\s+\S+(?:\s+\S+)?\s+(?:हैं|हो|बनिए){_END}"),

    # ---- Marathi (Devanagari) ----
    ("ignore_instructions", "mr",
     rf"(?:मागील|आधीच्या|पूर्वीच्या|वरील|सर्व)\s+(?:सर्व\s+)?{_MR_OBJ}\s*(?:विसर|दुर्लक्ष)"),
    ("reveal_prompt", "mr",
     r"(?:सिस्टम\s*प्रॉम्प्ट|(?:तुमच्या|तुझ्या|आतील|लपवलेल्या)\s+(?:सूचना|निर्देश|प्रॉम्प्ट))\s*"
     r"(?:दाखवा|दाखव|सांगा|सांग|लिहा)"),
    ("role_change", "mr",
     rf"आता\s+(?:पासून\s+)?(?:तू|तुम्ही)\s+(?:एक\s+)?\S+(?:\s+\S+){{0,2}}\s+(?:आहेस|आहात|हो|व्हा){_END}"),
]

def _prepare(rx: str) -> str:
    # Same Unicode clean-up as the text (NFC, no nukta), but no case-folding: it would turn
    # regex escapes such as \S or \W into \s / \w
    return unicodedata.normalize("NFC", rx).translate(_ZERO_WIDTH)


_COMPILED: list[tuple[str, str, re.Pattern[str]]] = [
    (name, lang, re.compile(_prepare(rx))) for name, lang, rx in INJECTION_PATTERNS
]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    return re.sub(r"\s+", " ", text).casefold()


def find_injection(text: str) -> tuple[str, str] | None:
    """(pattern name, language) of the first matching injection pattern, or None."""
    norm = normalize(text)
    for name, lang, rx in _COMPILED:
        if rx.search(norm):
            return name, lang
    return None

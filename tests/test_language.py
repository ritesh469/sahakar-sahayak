"""Question language detection (en / hi / mr / hinglish)."""

import pytest

from app.services.language import detect_language


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How much money does a farmer get under PM-KISAN?", "en"),
        ("What is the role of a primary agricultural credit society?", "en"),
        ("Who can become a member of a cooperative society?", "en"),
        ("पीएम किसान योजना में किसान को कितना पैसा मिलता है?", "hi"),
        ("राष्ट्रीय सहकारिता नीति 2025 का लक्ष्य क्या है?", "hi"),
        ("सहकारी समिति का सदस्य कौन बन सकता है?", "hi"),
        ("पीएम किसान योजनेत शेतकऱ्यांना वर्षाला किती रक्कम मिळते?", "mr"),
        ("सहकारी संस्थेच्या निवडणुकीसाठी पॅनेल कसे तयार केले जाते?", "mr"),
        ("कर्जमुक्ती योजनेचा लाभ कोणाला मिळतो?", "mr"),
        ("PM Kisan mein kitna paisa milta hai?", "hinglish"),
        ("Sahkari samiti ka member kaun ban sakta hai?", "hinglish"),
        ("Grain storage yojana ke liye kya documents chahiye?", "hinglish"),
        # P7 smoke test failures: scheme names are not Hinglish; Marathi without common words
        ("What minimum pension does a subscriber get under PM Kisan Maan-Dhan Yojana, and from "
         "what age?", "en"),
        ("महिला शेतकरी सक्षमीकरण अधिनियमानुसार राज्य संनियंत्रण समितीचे अध्यक्ष कोण असतात?", "mr"),
        ("बच्चों के लिए कौन सी योजना नीचे दी गई है?", "hi"),
        # answers: the Latin citation must not turn a Devanagari answer into English
        ("राज्य संनियंत्रण समिति (State Monitoring Committee) का अध्यक्ष मुख्य सचिव (Chief Secretary) "
         "होता है [mh_women_farmer_act_2026_en.pdf, p. 7].", "hi"),
    ],
)
def test_detect_language(question, expected):
    assert detect_language(question) == expected

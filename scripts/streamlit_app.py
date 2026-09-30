"""Streamlit UI for Sahakar Sahayak — Cooperative & Scheme Assistant.

A chat front end for the FastAPI backend (/auth, /query). Questions can be in English, Hindi,
Marathi or Hinglish; every answer shows the documents and pages it was built from as
"filename, p. N" stamps. Colours and fonts live in .streamlit/config.toml.
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any

import requests
import streamlit as st

from app.config import settings
from app.services.language import detect_language
from eval.metrics import extract_citations, refusal_type

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Root of the repo — used to find eval/results/*.json
_REPO_ROOT = Path(__file__).parent.parent

# Sidebar example questions, one per supported language (P6). All four were answered through the
# API on 2026-09-30. The Marathi one is question 3 of docs/DEMO_SCRIPT.md: the earlier e-KYC
# example was stopped by LLM Guard's English injection model (P14 false positive).
EXAMPLE_QUESTIONS: dict[str, str] = {
    "English": "How much income support does a farmer family get under PM-KISAN and how is it paid?",
    "हिंदी": "प्रधानमंत्री किसान सम्मान निधि योजना में किसानों को कितनी राशि मिलती है?",
    "मराठी": "महिला शेतकरी सक्षमीकरण अधिनियमानुसार राज्य संनियंत्रण समितीचे अध्यक्ष कोण असतात?",
    "Hinglish": "Grain storage plan mein PACS ko kya kya facilities banane ki permission hai?",
}

LANG_LABELS = {"en": "English", "hi": "हिंदी", "mr": "मराठी", "hinglish": "Hinglish"}

# Demo agent from scripts/seed_db.py DEMO_USERS (local demo only), pre-filled in the sign-in form
DEMO_USERNAME = "agent@demo.local"
DEMO_PASSWORD = "agent123"

SEARCH_MODE_LABELS = {
    "hybrid": "Hybrid: meaning + keywords",
    "dense": "Dense: meaning only (bge-m3)",
    "bm25": "BM25: keywords only",
    "tfidf": "TF-IDF: old keyword baseline",
    "sparse": "Sparse: keywords only",
}
SEARCH_MODE_SHORT = {"hybrid": "Hybrid search", "dense": "Dense search", "bm25": "BM25 search",
                     "tfidf": "TF-IDF search", "sparse": "Sparse search"}
DEFAULT_SEARCH_MODES = ["dense", "hybrid"]

# Best setup in the experiments (Exp 3: hybrid + reranker, 5 passages); also the demo setting
DEFAULT_QUERY_SETTINGS: dict[str, Any] = {
    "search_mode": "hybrid",
    "top_k": 5,
    "enable_rerank": True,
    "enable_hyde": False,
    "enable_crag": False,
    "enable_self_reflective": False,
}

# Shown above a refusal (eval.metrics.refusal_type), so it is not mistaken for a normal answer
REFUSAL_NOTES = {
    "no_info": ("Not in the documents",
                "The assistant read the passages below and did not find this. It answers only "
                "from the documents, so it does not guess."),
    "out_of_domain": ("Outside this assistant's topic",
                      "It answers questions about cooperatives and government schemes only."),
}

# ---------------------------------------------------------------------------
# Look and feel
# ---------------------------------------------------------------------------

# Answers are stamped with their sources the way a government office stamps a file: violet ink,
# double rule, never quite straight. Everything else stays quiet. Theme colours and the Mukta /
# IBM Plex Mono fonts come from .streamlit/config.toml; Rozha One is only for the wordmark.
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Rozha+One&display=swap');
:root {
  --ss-ink: #1C2433; --ss-muted: #5B6472;
  --ss-stamp: #5A3D8A; --ss-stamp-wash: rgba(90, 61, 138, 0.07);
  --ss-field: #2F6D4F; --ss-turmeric: #B7791F; --ss-turmeric-wash: #FBF1DC;
}
/* "[data-testid=stMarkdownContainer] p" outranks Streamlit's own paragraph size and margin */
[data-testid="stMarkdownContainer"] p.ss-wordmark { font-family: 'Rozha One', 'Nirmala UI', serif;
  font-weight: 400; color: var(--ss-ink); line-height: 1.15; margin: 0; }
[data-testid="stMarkdownContainer"] p.ss-wordmark--hero { font-size: clamp(2.8rem, 9vw, 4.4rem);
  margin-top: .5rem; }
[data-testid="stMarkdownContainer"] p.ss-wordmark--side { font-size: 1.9rem; }
[data-testid="stMarkdownContainer"] p.ss-latin { font-size: .74rem; font-weight: 600;
  letter-spacing: .14em; text-transform: uppercase; color: var(--ss-muted); margin: .15rem 0 0; }
[data-testid="stMarkdownContainer"] p.ss-lede { font-size: 1.25rem; line-height: 1.45;
  max-width: 36rem; margin: 1.1rem 0 .4rem; }
[data-testid="stMarkdownContainer"] p.ss-note { color: var(--ss-muted); max-width: 36rem;
  margin: 0 0 1rem; }
[data-testid="stMarkdownContainer"] p.ss-status { font-size: .85rem; font-weight: 500;
  margin: .6rem 0 .2rem; }
.ss-status::before { content: ""; display: inline-block; width: .5rem; height: .5rem;
  border-radius: 50%; background: currentColor; margin-right: .45rem; vertical-align: .08rem; }
.ss-status--ok { color: var(--ss-field); }
.ss-status--down { color: var(--ss-turmeric); }
[data-testid="stMarkdownContainer"] p.ss-label { font-size: .72rem; font-weight: 600;
  letter-spacing: .12em; text-transform: uppercase; color: var(--ss-muted); margin: 1rem 0 .15rem; }
[data-testid="stMarkdownContainer"] p.ss-lang { font-size: .72rem; font-weight: 600;
  letter-spacing: .1em; text-transform: uppercase; color: var(--ss-muted); margin: 0 0 .1rem; }
[data-testid="stMarkdownContainer"] p.ss-meta { font-size: .85rem; color: var(--ss-muted);
  margin: .5rem 0 .2rem; }
/* Example questions read as a list, not as centred buttons */
[class*="st-key-example_"] button { justify-content: flex-start; text-align: left; }
[class*="st-key-example_"] button p { text-align: left; }
.ss-stamps { display: flex; flex-wrap: wrap; gap: .8rem .9rem; margin: .4rem 0 .3rem; padding: 2px; }
.ss-stamp { display: inline-block; max-width: 100%; overflow-wrap: anywhere;
  padding: .3rem .7rem; color: var(--ss-stamp); background: var(--ss-stamp-wash);
  border: 3px double var(--ss-stamp); border-radius: 3px;
  font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .78rem; font-weight: 500;
  line-height: 1.3; transform: rotate(-1deg); }
.ss-stamp:nth-child(3n+2) { transform: rotate(.7deg); }
.ss-stamp:nth-child(3n) { transform: rotate(-.4deg); }
.ss-cite { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .8em;
  color: var(--ss-stamp); background: var(--ss-stamp-wash); border-radius: 3px;
  padding: .05em .35em; overflow-wrap: anywhere; }
.ss-cite + .ss-cite { margin-left: .3em; }
.ss-notice { border-left: 4px solid var(--ss-turmeric); background: var(--ss-turmeric-wash);
  color: #3F2E00; padding: .6rem .9rem; border-radius: 0 6px 6px 0; margin: .1rem 0 .7rem; }
.ss-notice strong { display: block; margin-bottom: .1rem; }
</style>
"""

# ---------------------------------------------------------------------------
# API feature detection
# ---------------------------------------------------------------------------


@st.cache_data(ttl=15)
def detect_api_features(base_url: str) -> dict:
    """Probe /openapi.json: is the server up, which query flags and search modes does it accept?"""
    try:
        r = requests.get(f"{base_url.rstrip('/')}/openapi.json", timeout=5)
    except requests.exceptions.RequestException:
        return {"reachable": False, "available_flags": set(), "search_modes": DEFAULT_SEARCH_MODES}
    if r.status_code != 200:
        return {"reachable": False, "available_flags": set(), "search_modes": DEFAULT_SEARCH_MODES}
    spec = r.json()
    qr_schema = spec.get("components", {}).get("schemas", {}).get("QueryRequest", {}) or {}
    props = qr_schema.get("properties", {})
    return {
        "reachable": True,
        "available_flags": set(props),
        # bm25 / tfidf appear once the backend has them (P8)
        "search_modes": props.get("search_mode", {}).get("enum") or DEFAULT_SEARCH_MODES,
    }


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _api_headers(token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"text": resp.text}


def _login(base_url: str, username: str, password: str) -> tuple[int, Any]:
    return _request(
        "POST",
        base_url,
        "/auth/login",
        json_body={"username": username, "password": password},
        retry_auth=False,
    )


def _refresh_token(base_url: str) -> bool:
    username = st.session_state.get("login_username")
    password = st.session_state.get("login_password")
    if not username or not password:
        return False
    status, payload = _login(base_url, username, password)
    if status == 200 and isinstance(payload, dict) and "token" in payload:
        st.session_state["token"] = payload["token"]
        return True
    return False


def _send(method: str, url: str, token: str | None, json_body: dict[str, Any] | None,
          files: dict[str, Any] | None) -> tuple[int, Any]:
    """One HTTP call. Status 0 = the server could not be reached or did not answer in time."""
    headers = _api_headers(token)
    if files is not None:
        headers.pop("Content-Type", None)
    try:
        resp = requests.request(method=method, url=url, headers=headers, json=json_body,
                                files=files, timeout=600)
    except requests.exceptions.ConnectionError:
        return 0, {"detail": "connection_error"}
    except requests.exceptions.Timeout:
        return 0, {"detail": "timeout"}
    return resp.status_code, _safe_json(resp)


def _request(
    method: str,
    base_url: str,
    path: str,
    token: str | None = None,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    retry_auth: bool = True,
) -> tuple[int, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    status, payload = _send(method, url, token, json_body, files)
    if (
        retry_auth
        and status == 401
        and isinstance(payload, dict)
        and payload.get("detail") == "Token has expired"
        and _refresh_token(base_url)
    ):
        status, payload = _send(method, url, st.session_state.get("token"), json_body, files)
    return status, payload


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _badge(label: str, color: str = "blue") -> str:
    """Return a small HTML badge (used by the evaluation dashboard)."""
    colors = {
        "blue": "#dbeafe",
        "text_blue": "#1e40af",
        "green": "#d1fae5",
        "text_green": "#065f46",
        "yellow": "#fef9c3",
        "text_yellow": "#854d0e",
        "red": "#fee2e2",
        "text_red": "#991b1b",
        "purple": "#f3e8ff",
        "text_purple": "#6b21a8",
    }
    bg = colors.get(color, colors["blue"])
    fg = colors.get(f"text_{color}", colors["text_blue"])
    return f"""
    <span style="
        background-color: {bg};
        color: {fg};
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
        white-space: nowrap;
    ">{label}</span>
    """


def _format_source(chunk: dict[str, Any]) -> str:
    """'filename, p. N' (or just the filename for formats without pages)."""
    source = chunk.get("source", "?")
    page = chunk.get("page_number")
    return f"{source}, p. {page}" if page is not None else source


def _format_sources(chunks: list[dict[str, Any]]) -> list[str]:
    """Unique 'filename, p. N' entries in retrieval order."""
    return list(dict.fromkeys(_format_source(ch) for ch in chunks))


def _cited_sources(answer: str) -> list[str]:
    """Unique 'filename, p. N' for the [file, p. N] citations written in the answer."""
    return list(dict.fromkeys(f"{c.source}, p. {c.page}" if c.page is not None else c.source
                              for c in extract_citations(answer)))


# [file.pdf, p. 3] inside an answer -> a small violet tag (same shape as eval.metrics citations)
_INLINE_CITE = re.compile(r"\[([^\[\]\n]+?\.(?:pdf|docx|html?|txt|md)(?:\s*,\s*pp?\.?\s*[\d,\s–-]+)?)\]",
                          re.I)


def _answer_html(answer: str) -> str:
    """Answer markdown with HTML escaped (it can quote document text) and citations as tags."""
    safe = html.escape(answer, quote=False)
    return _INLINE_CITE.sub(lambda m: f'<span class="ss-cite">{m.group(1)}</span>', safe)


def _notice(title: str, body: str) -> None:
    st.markdown(
        f'<div class="ss-notice" role="status"><strong>{html.escape(title)}</strong>'
        f"{html.escape(body)}</div>",
        unsafe_allow_html=True,
    )


def _stamps(labels: list[str]) -> None:
    items = "".join(f'<span class="ss-stamp">{html.escape(label)}</span>' for label in labels)
    st.markdown(f'<p class="ss-label">Sources</p><div class="ss-stamps">{items}</div>',
                unsafe_allow_html=True)


def _render_answer(payload: dict[str, Any], turn: dict[str, Any] | None = None) -> None:
    """Answer text, source stamps, a one-line summary of how it was found, and the passages."""
    answer = payload.get("answer") or ""
    meta = payload.get("metadata") or {}
    chunks = meta.get("retrieved_chunks") or []
    kind = refusal_type(answer) if answer else None

    if kind:
        _notice(*REFUSAL_NOTES[kind])
    if answer:
        st.markdown(_answer_html(answer), unsafe_allow_html=True)
    else:
        st.markdown("_The server returned an empty answer._")
    if not kind:
        sources = _cited_sources(answer) or _format_sources(chunks) or payload.get("sources", [])
        if sources:
            _stamps(sources)

    used = (turn or {}).get("settings", {})
    parts = []
    if used.get("search_mode"):
        parts.append(SEARCH_MODE_SHORT.get(used["search_mode"], used["search_mode"]))
    if used.get("enable_rerank"):
        parts.append("reranked")
    parts.append(f"{len(chunks)} passage{'s' if len(chunks) != 1 else ''} read")
    if meta.get("reflection_iterations"):
        parts.append(f"{meta['reflection_iterations']} review round(s)")
    if payload.get("cache_hit"):
        parts.append("from cache")
    if turn and turn.get("seconds") is not None:
        parts.append(f"{turn['seconds']:.1f} s")
    st.markdown(f'<p class="ss-meta">{html.escape(" · ".join(parts))}</p>', unsafe_allow_html=True)

    if chunks:
        with st.expander(f"Passages read ({len(chunks)})"):
            for i, ch in enumerate(chunks, 1):
                st.markdown(
                    f'<p class="ss-meta"><span class="ss-cite">{html.escape(_format_source(ch))}'
                    f'</span> &nbsp;score {ch.get("score", 0.0):.3f}</p>',
                    unsafe_allow_html=True,
                )
                st.markdown(ch.get("text", ""))
                if i < len(chunks):
                    st.divider()
    with st.expander("Technical details"):
        st.json({"settings": used, "response": payload} if turn else payload)


def _render_error(status: int, payload: Any) -> None:
    """Explain a failed request in plain words; the raw response stays one click away."""
    detail = payload.get("detail") if isinstance(payload, dict) else None
    text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
    if status == 0 and detail == "connection_error":
        title, body = ("Can't reach the assistant server",
                       "Start the API (port 8001) and ask again. Its address is under Server in "
                       "the sidebar.")
    elif status == 0:
        title, body = "The server took too long", "Wait a moment and ask again."
    elif status == 422 and "malicious" in text:
        title, body = ("Blocked by the safety check",
                       "The question looks like an attempt to change the assistant's instructions, "
                       "so it was not sent to the language model. Ask about a cooperative or a "
                       "scheme instead.")
    elif status == 400 and text.startswith("injection_blocked"):
        title, body = ("Blocked by the safety filter",
                       "LLM Guard's prompt-injection check stopped this question before it reached "
                       "the assistant. The check is trained on English and sometimes blocks normal "
                       "Hindi or Marathi questions; rewording the question can help.")
    elif status == 400 and text.startswith("content_blocked"):
        title, body = ("Blocked by the content filter",
                       "The toxicity or personal-data check stopped this question.")
    elif status == 429:
        title, body = ("Too many questions at once",
                       text if "tokens" in text else "Wait a minute and ask again.")
    elif status == 401:
        title, body = "Your sign-in has expired", "Sign out in the sidebar and sign in again."
    elif status == 500 and "output_blocked" in text:
        title, body = "Answer withheld", "The output filter blocked the generated answer."
    else:
        title, body = "Something went wrong", f"The server answered with HTTP {status}."
    _notice(title, body)
    with st.expander("Technical details"):
        st.json(payload)


def _render_pending_sql_card(pending_sql: dict[str, Any]) -> None:
    """Render a pending SQL approval card."""
    st.warning("SQL approval required — open the **SQL approval** tab to review it.")
    with st.container(border=True):
        st.markdown("**Generated SQL**")
        st.code(pending_sql.get("sql", ""), language="sql")
        st.caption(f"query_id: `{pending_sql.get('query_id', '')}`")
        if pending_sql.get("explanation"):
            st.info(pending_sql["explanation"])


def _render_response_card(status: int, payload: Any, turn: dict[str, Any] | None = None) -> None:
    """Answer, pending SQL block or error for one API response."""
    if not isinstance(payload, dict):
        st.code(json.dumps(payload, indent=2), language="json")
        return
    if not 200 <= status < 300:
        _render_error(status, payload)
        return
    pending_sql = payload.get("pending_sql")
    if pending_sql:
        st.session_state["pending_sql"] = pending_sql
        _render_pending_sql_card(pending_sql)
        return
    _render_answer(payload, turn)


# ---------------------------------------------------------------------------
# Sidebar, sign-in and chat
# ---------------------------------------------------------------------------


def _hero() -> None:
    st.markdown(
        '<p class="ss-wordmark ss-wordmark--hero" lang="hi">सहकार सहायक</p>'
        '<p class="ss-latin">Sahakar Sahayak · Cooperative &amp; scheme assistant</p>'
        '<p class="ss-lede">Ask about cooperative societies and government schemes in English, '
        '<span lang="hi">हिंदी</span>, <span lang="mr">मराठी</span> or Hinglish.</p>'
        '<p class="ss-note">Answers come only from official Acts, policies, scheme guidelines and '
        "government resolutions. Every fact is stamped with the file and page it came from, and "
        "when the documents don't say, the assistant tells you so.</p>",
        unsafe_allow_html=True,
    )


def _settings_panel(info: dict) -> dict[str, Any]:
    """Search settings in the sidebar; returns the flags to send with each question."""
    flags = info.get("available_flags") or set()

    def supported(flag: str) -> bool:
        return not flags or flag in flags

    for key, value in DEFAULT_QUERY_SETTINGS.items():
        st.session_state.setdefault(f"q_{key}", value)
    modes = list(info.get("search_modes") or DEFAULT_SEARCH_MODES)
    if st.session_state["q_search_mode"] not in modes:
        st.session_state["q_search_mode"] = modes[0]

    with st.expander("Search settings"):
        st.caption("The defaults are the best setup from the experiments: hybrid search with the "
                   "reranker, reading 5 passages.")
        if supported("search_mode"):
            st.selectbox("How to search the documents", modes,
                         format_func=lambda m: SEARCH_MODE_LABELS.get(m, m), key="q_search_mode")
        if supported("top_k"):
            st.slider("Passages to read", min_value=1, max_value=20, key="q_top_k")
        if supported("enable_rerank"):
            st.toggle("Rerank passages", key="q_enable_rerank",
                      help="A cross-encoder (bge-reranker-v2-m3) re-orders the passages found.")
        st.markdown('<p class="ss-label">Extra steps (slower)</p>', unsafe_allow_html=True)
        if supported("enable_hyde"):
            st.toggle("HyDE", key="q_enable_hyde",
                      help="Search with a draft answer written by the model.")
        if supported("enable_crag"):
            st.toggle("CRAG", key="q_enable_crag",
                      help="A grader model drops passages it judges irrelevant (no web search).")
        if supported("enable_self_reflective"):
            st.toggle("Self-RAG", key="q_enable_self_reflective",
                      help="A reviewer model checks the answer and may ask for a retry.")

    return {key: st.session_state[f"q_{key}"] for key in DEFAULT_QUERY_SETTINGS if supported(key)}


def _sidebar(info: dict) -> dict[str, Any]:
    """Wordmark, example questions, search settings, account and server. Returns query settings."""
    with st.sidebar:
        st.markdown(
            '<p class="ss-wordmark ss-wordmark--side" lang="hi">सहकार सहायक</p>'
            '<p class="ss-latin">Sahakar Sahayak</p>',
            unsafe_allow_html=True,
        )
        if info.get("reachable"):
            st.markdown('<p class="ss-status ss-status--ok">Server connected</p>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<p class="ss-status ss-status--down">Server not reachable</p>',
                        unsafe_allow_html=True)

        st.markdown('<p class="ss-label">Try a question</p>', unsafe_allow_html=True)
        for lang, question in EXAMPLE_QUESTIONS.items():
            if st.button(f"**{lang}** · {question}", key=f"example_{lang}",
                         use_container_width=True):
                st.session_state["pending_question"] = question

        query_settings = _settings_panel(info)

        if st.session_state.get("token"):
            st.divider()
            user = html.escape(st.session_state.get("login_username", "user"))
            st.markdown(f'<p class="ss-meta">Signed in as {user}</p>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            if c1.button("New chat", use_container_width=True):
                st.session_state["chat"] = []
            if c2.button("Sign out", use_container_width=True):
                st.session_state.clear()
                st.rerun()

        with st.expander("Server"):
            st.text_input("API address", key="base_url_input")
            api = st.session_state["base_url_input"].rstrip("/")
            st.markdown(f"[API docs]({api}/docs) · [ReDoc]({api}/redoc)")
            if st.button("Check server", use_container_width=True):
                status, payload = _request("GET", api, "/admin/health")
                if status == 200 and isinstance(payload, dict):
                    if payload.get("status") == "ok":
                        st.success("All parts are working.")
                    else:
                        st.warning(f"Partly working: {payload.get('status')}")
                    st.json({k: v for k, v in payload.items() if k != "status"})
                else:
                    st.error("The health check failed. Is the API running?")
    return query_settings


def _auth_error(status: int, payload: Any) -> None:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    messages = {
        0: "Can't reach the assistant server. Start the API (port 8001) and try again.",
        401: "Wrong username or password.",
        409: "That username is already taken.",
        429: "Too many sign-in attempts. Wait a minute and try again.",
    }
    st.error(messages.get(status, f"Sign-in failed (HTTP {status}): {detail}"))


def _sign_in_screen(base_url: str) -> None:
    _hero()
    with st.form("sign_in"):
        st.markdown("**Sign in to ask questions**")
        username = st.text_input("Username", value=DEMO_USERNAME)
        password = st.text_input("Password", value=DEMO_PASSWORD, type="password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    st.caption("The demo account from scripts/seed_db.py is filled in.")
    if submitted:
        status, payload = _login(base_url, username, password)
        if status == 200 and isinstance(payload, dict) and "token" in payload:
            st.session_state["token"] = payload["token"]
            st.session_state["login_username"] = username
            st.session_state["login_password"] = password
            st.rerun()
        _auth_error(status, payload)

    with st.expander("Create an account"):
        with st.form("register"):
            new_user = st.text_input("Username", key="reg_user")
            new_pass = st.text_input("Password", type="password", key="reg_pass")
            created = st.form_submit_button("Create account", use_container_width=True)
        if created:
            status, payload = _request(
                "POST", base_url, "/auth/register",
                json_body={"username": new_user, "password": new_pass},
            )
            if status in (200, 201) and isinstance(payload, dict) and "token" in payload:
                st.session_state["token"] = payload["token"]
                st.session_state["login_username"] = new_user
                st.session_state["login_password"] = new_pass
                st.rerun()
            _auth_error(status, payload)


def _render_question(question: str) -> None:
    lang = LANG_LABELS.get(detect_language(question), "")
    st.markdown(f'<p class="ss-lang">{html.escape(lang)}</p>', unsafe_allow_html=True)
    st.markdown(question)


def _chat_section(base_url: str, query_settings: dict[str, Any]) -> None:
    """The conversation: earlier turns, then the new question (typed or an example)."""
    chat: list[dict[str, Any]] = st.session_state.setdefault("chat", [])
    # The input box is pinned to the bottom wherever it is created; reading it first lets the
    # welcome text disappear as soon as the first question is asked
    typed = st.chat_input("Ask in English, हिंदी, मराठी or Hinglish…")
    question = (st.session_state.pop("pending_question", None) or typed or "").strip()
    if not chat and not question:
        _hero()
        st.caption("Pick an example question in the sidebar, or type your own below.")

    for turn in chat:
        with st.chat_message("user", avatar=":material/person:"):
            _render_question(turn["question"])
        with st.chat_message("assistant", avatar=":material/account_balance:"):
            _render_response_card(turn["status"], turn["payload"], turn)

    if not question:
        return

    turn: dict[str, Any] = {"question": question, "settings": dict(query_settings)}
    with st.chat_message("user", avatar=":material/person:"):
        _render_question(question)
    with st.chat_message("assistant", avatar=":material/account_balance:"):
        with st.spinner("Searching the documents…"):
            started = time.perf_counter()
            status, payload = _request(
                "POST", base_url, "/query",
                token=st.session_state.get("token"),
                json_body={"question": question, **query_settings},
            )
            turn["seconds"] = time.perf_counter() - started
        turn["status"], turn["payload"] = status, payload
        _render_response_card(status, payload, turn)
    chat.append(turn)


def _upload_section(base_url: str) -> None:
    st.header("📤 Upload Document")
    token = st.session_state.get("token")
    if not token:
        st.info("Login first to upload documents.")
        return

    uploaded = st.file_uploader("Choose a PDF", type=["pdf"], key="pdf_uploader")

    if uploaded is None:
        st.caption("Select a PDF above to see upload options.")
        return

    # File info card
    size_kb = len(uploaded.getvalue()) / 1024
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            st.markdown(f"**📄 {uploaded.name}**")
        with c2:
            st.markdown(f"`{size_kb:.1f} KB`")
        with c3:
            st.markdown("`PDF ✅`")

    # First-run warning
    st.info(
        "⏱️ **First upload may take 1–3 minutes** — Docling downloads OCR/layout models (~400 MB) on first use. "
        "Subsequent uploads are typically under 10 seconds.",
        icon="⏳",
    )

    if st.button("🚀 Upload & Index", use_container_width=True, key="btn_upload"):
        files = {"file": (uploaded.name, uploaded.getvalue(), "application/pdf")}

        with st.status("Indexing document…", expanded=True) as status:
            st.write("📡 **Step 1/3** — Sending file to API…")

            try:
                resp = requests.request(
                    method="POST",
                    url=f"{base_url.rstrip('/')}/documents/upload",
                    headers={"Authorization": f"Bearer {token}"},
                    files=files,
                    timeout=600,
                )
                status_code = resp.status_code
                payload = _safe_json(resp)
            except requests.exceptions.Timeout:
                status.update(label="⏱️ Upload timed out", state="error", expanded=True)
                st.error(
                    "The upload timed out after 10 minutes. This usually means Docling is still downloading models.\n\n"
                    "**What to do:**\n"
                    "1. Check the API server logs — you should see Docling download progress\n"
                    "2. Wait for the download to finish (one-time only)\n"
                    "3. Try uploading again — it will be fast after models are cached"
                )
                return
            except requests.exceptions.ConnectionError:
                status.update(label="❌ Connection failed", state="error", expanded=True)
                st.error("Could not connect to the API. Is the server running at the configured base URL?")
                return

            if status_code in (200, 201) and isinstance(payload, dict):
                chunks = payload.get("chunks_indexed", 0)
                page_count = payload.get("page_count")
                doc_id = payload.get("doc_id", uploaded.name)

                st.write(f"✅ **Step 2/3** — Parsed {chunks} chunk(s)" + (f" from {page_count} page(s)" if page_count else ""))
                st.write("✅ **Step 3/3** — Embeddings created & vectors upserted to Qdrant")
                status.update(label=f"🎉 Indexed {chunks} chunks successfully", state="complete")

                with st.container(border=True):
                    st.markdown("**🎉 Document Indexed**")
                    cols = st.columns([3, 1, 1])
                    with cols[0]:
                        st.markdown(f"`{doc_id}`")
                    with cols[1]:
                        st.metric("Chunks", chunks)
                    with cols[2]:
                        st.metric("Pages", page_count or "—")
                    st.caption("The document is now searchable via the Query tab.")
            else:
                status.update(label=f"❌ Upload failed (HTTP {status_code})", state="error", expanded=True)
                _render_response_card(status_code, payload)


def _sql_approval_section(base_url: str) -> None:
    st.header("🗄️ SQL Approval")
    token = st.session_state.get("token")
    pending = st.session_state.get("pending_sql")

    if not token:
        st.info("Login first.")
        return

    # --- Show previously approved / rejected result --------------------------
    last_sql = st.session_state.get("last_sql_result")
    if last_sql and isinstance(last_sql, dict):
        action = last_sql.get("action", "approved")
        label = "✅ Approved Result" if action == "approved" else "❌ Rejected Result"
        with st.container(border=True):
            st.markdown(f"**{label}**")
            st.caption(f"query_id: `{last_sql.get('query_id', '—')}`")
            if action == "approved":
                _render_answer(last_sql["payload"])
            else:
                st.markdown("_SQL query was rejected._")
        if st.button("🗑️ Dismiss result", key="dismiss_sql_result"):
            st.session_state.pop("last_sql_result", None)
            st.rerun()
        st.divider()

    if not pending:
        st.info(
            "No pending SQL block. Ask a data question (e.g. *How many P1 incidents last month?*) "
            "to trigger Text2SQL."
        )
        return

    with st.container(border=True):
        st.markdown("### ⏳ Pending SQL Review")
        st.code(pending.get("sql", ""), language="sql")
        st.caption(f"query_id: `{pending.get('query_id', '')}`")
        if pending.get("explanation"):
            st.info(pending["explanation"])

        c_approve, c_reject = st.columns(2)
        with c_approve:
            if st.button("✅ Approve & Execute", use_container_width=True, type="primary"):
                with st.spinner("Executing SQL…"):
                    status, payload = _request(
                        "POST", base_url, "/query/sql/execute",
                        token=token,
                        json_body={"query_id": pending.get("query_id"), "approved": True},
                    )
                _render_response_card(status, payload)
                if 200 <= status < 300 and isinstance(payload, dict):
                    st.session_state["last_sql_result"] = {
                        "query_id": pending.get("query_id"),
                        "action": "approved",
                        "payload": payload,
                    }
                    st.session_state.pop("pending_sql", None)
                    st.rerun()
        with c_reject:
            if st.button("❌ Reject", use_container_width=True):
                with st.spinner("Rejecting…"):
                    status, payload = _request(
                        "POST", base_url, "/query/sql/execute",
                        token=token,
                        json_body={"query_id": pending.get("query_id"), "approved": False},
                    )
                _render_response_card(status, payload)
                if 200 <= status < 300:
                    st.session_state["last_sql_result"] = {
                        "query_id": pending.get("query_id"),
                        "action": "rejected",
                        "payload": {},
                    }
                    st.session_state.pop("pending_sql", None)
                    st.rerun()


# ---------------------------------------------------------------------------
# Eval Dashboard helpers
# ---------------------------------------------------------------------------


def _list_eval_files() -> list[Path]:
    """Return every *.json file in eval/results/, sorted newest first
    (by mtime, with `lesson-N-*-baseline.json` deprioritised vs. fresh runs).
    """
    results_dir = _REPO_ROOT / "eval" / "results"
    if not results_dir.exists():
        return []
    files = [p for p in results_dir.glob("*.json") if p.is_file()]
    # Newest first by mtime
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _load_eval_file(path: Path) -> dict | None:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _format_result_choice(path: Path) -> str:
    """Pretty label for a result file in a selectbox."""
    data = _load_eval_file(path)
    if not data:
        return f"{path.name} (unreadable)"
    profile = data.get("profile", "?")
    ts = data.get("timestamp_utc", "")
    ts_short = ts[:19].replace("T", " ") if ts else ""
    return f"{path.name}  ·  profile={profile}  ·  {ts_short}"


def _row_status(row: dict) -> str:
    """Single-letter status for a golden row based on RAGAS + post-checks."""
    ragas = row.get("ragas_metrics") or {}
    faith = ragas.get("faithfulness") or 0
    ans_rel = ragas.get("answer_relevancy") or 0
    forbidden_ok = (row.get("forbidden_check") or {}).get("passed", True)
    if not forbidden_ok:
        return "❌ forbidden"
    score = max(faith, ans_rel)  # be lenient for SQL goldens where one of the two is null
    if score >= 0.7:
        return "✅ Pass"
    if score >= 0.4:
        return "🟡 Partial"
    return "❌ Fail"


def _eval_dashboard_section() -> None:
    """Golden-centric Eval Dashboard — view goldens, pick a result file,
    optionally compare to a previous run."""
    st.header("📊 Evaluation Results")
    st.caption(
        "Browse every golden question + its score in any eval result file. "
        "Latest run is the default; switch to compare against earlier runs."
    )

    files = _list_eval_files()
    if not files:
        st.warning(
            "No eval result files in `eval/results/`. "
            "Run `make eval-baseline` (or any `make eval-*` target) to generate one."
        )
        return

    # -------------------------------------------------------------------------
    # Result file selection (latest = default)
    # -------------------------------------------------------------------------
    c1, c2 = st.columns(2)
    with c1:
        latest_path = st.selectbox(
            "📄 Latest result file",
            files,
            index=0,
            format_func=_format_result_choice,
            key="eval_latest_select",
        )
    with c2:
        prev_options = [None] + [p for p in files if p != latest_path]
        prev_path = st.selectbox(
            "📄 Compare with previous (optional)",
            prev_options,
            format_func=lambda p: "— none —" if p is None else _format_result_choice(p),
            key="eval_prev_select",
        )

    latest_data = _load_eval_file(latest_path) if latest_path else None
    prev_data = _load_eval_file(prev_path) if prev_path else None
    if not latest_data:
        st.error(f"Could not load `{latest_path.name}`.")
        return

    # -------------------------------------------------------------------------
    # Aggregate header
    # -------------------------------------------------------------------------
    agg = latest_data.get("aggregate") or {}
    n_scored = agg.get("evaluated", len(latest_data.get("rows", [])))
    n_skipped = len(latest_data.get("skipped", []))

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Faithfulness", f"{agg.get('faithfulness', 0):.2f}")
    m2.metric("Ctx Precision", f"{agg.get('context_precision', 0):.2f}")
    m3.metric("Ctx Recall", f"{agg.get('context_recall', 0):.2f}")
    m4.metric("Ans Relevancy", f"{agg.get('answer_relevancy', 0):.2f}")
    m5.metric("Scored / Skipped", f"{n_scored} / {n_skipped}")

    # If comparing with a previous run, show the deltas
    if prev_data:
        prev_agg = prev_data.get("aggregate") or {}

        def _delta(a: float, b: float) -> str:
            d = a - b
            sign = "+" if d >= 0 else ""
            return f"{sign}{d:.2f}"

        st.caption(
            f"vs previous: "
            f"faith {_delta(agg.get('faithfulness', 0), prev_agg.get('faithfulness', 0))} · "
            f"prec {_delta(agg.get('context_precision', 0), prev_agg.get('context_precision', 0))} · "
            f"recall {_delta(agg.get('context_recall', 0), prev_agg.get('context_recall', 0))} · "
            f"ans_rel {_delta(agg.get('answer_relevancy', 0), prev_agg.get('answer_relevancy', 0))}"
        )

    st.markdown("---")

    # -------------------------------------------------------------------------
    # Filters
    # -------------------------------------------------------------------------
    rows = latest_data.get("rows", [])
    skipped_items = latest_data.get("skipped", [])

    # Build prev row lookup for comparison
    prev_rows_by_id: dict[str, dict] = {}
    if prev_data:
        for r in prev_data.get("rows", []):
            qid = r.get("id")
            if qid:
                prev_rows_by_id[qid] = r

    features = sorted({(r.get("demonstrates_feature") or "?") for r in rows})
    intents = sorted({(r.get("intent") or "?") for r in rows})
    statuses = ["✅ Pass", "🟡 Partial", "❌ Fail", "❌ forbidden"]

    f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
    with f1:
        sel_features = st.multiselect("Filter by feature", features, default=features, key="eval_filter_feature")
    with f2:
        sel_intents = st.multiselect("Filter by intent", intents, default=intents, key="eval_filter_intent")
    with f3:
        sel_statuses = st.multiselect("Filter by status", statuses, default=statuses, key="eval_filter_status")
    with f4:
        include_skipped = st.toggle("Show skipped", value=False, key="eval_show_skipped")

    # -------------------------------------------------------------------------
    # Table
    # -------------------------------------------------------------------------
    def _fmt(v: Any) -> str:
        return f"{v:.2f}" if isinstance(v, (int, float)) else "—"

    table_rows = []
    for r in rows:
        status = _row_status(r)
        if status not in sel_statuses:
            continue
        if (r.get("demonstrates_feature") or "?") not in sel_features:
            continue
        if (r.get("intent") or "?") not in sel_intents:
            continue

        ragas = r.get("ragas_metrics") or {}
        prev_r = prev_rows_by_id.get(r.get("id"))
        prev_ragas = (prev_r or {}).get("ragas_metrics") or {}

        def _delta_cell(curr: Any, prev: Any) -> str:
            if not prev_data or not isinstance(curr, (int, float)) or not isinstance(prev, (int, float)):
                return _fmt(curr)
            diff = curr - prev
            sign = "↑" if diff > 0 else ("↓" if diff < 0 else "·")
            return f"{curr:.2f} ({sign}{abs(diff):.2f})"

        table_rows.append({
            "ID": r.get("id", ""),
            "Status": status,
            "Feature": r.get("demonstrates_feature", "?"),
            "Intent": r.get("intent", "?"),
            "Question": (r.get("question") or "")[:90],
            "Faith": _delta_cell(ragas.get("faithfulness"), prev_ragas.get("faithfulness")),
            "Prec": _delta_cell(ragas.get("context_precision"), prev_ragas.get("context_precision")),
            "Recall": _delta_cell(ragas.get("context_recall"), prev_ragas.get("context_recall")),
            "Ans Rel": _delta_cell(ragas.get("answer_relevancy"), prev_ragas.get("answer_relevancy")),
        })

    if include_skipped:
        for s in skipped_items:
            sid = s.get("id") if isinstance(s, dict) else str(s)
            reason = s.get("reason") if isinstance(s, dict) else ""
            table_rows.append({
                "ID": sid or "",
                "Status": "⏭ Skipped",
                "Feature": "—",
                "Intent": "—",
                "Question": (reason or "")[:90],
                "Faith": "—",
                "Prec": "—",
                "Recall": "—",
                "Ans Rel": "—",
            })

    st.caption(f"Showing **{len(table_rows)}** goldens.")
    st.dataframe(table_rows, use_container_width=True, hide_index=True, height=420)

    # -------------------------------------------------------------------------
    # Drill-down — full detail for one golden
    # -------------------------------------------------------------------------
    st.markdown("---")
    st.subheader("🔍 Drill-down")

    all_ids = [r.get("id", "") for r in rows if r.get("id")]
    if not all_ids:
        st.caption("No goldens in this result file.")
        return

    sel_id = st.selectbox(
        "Inspect a specific golden",
        all_ids,
        format_func=lambda qid: (
            f"{qid} — "
            + ((next((r.get('question', '')[:80] for r in rows if r.get('id') == qid), ""))
               or "")
        ),
        key="eval_drilldown_select",
    )

    if not sel_id:
        return

    sel_row = next((r for r in rows if r.get("id") == sel_id), None)
    if not sel_row:
        return

    ragas = sel_row.get("ragas_metrics") or {}
    prev_sel = prev_rows_by_id.get(sel_id) or {}
    prev_ragas = prev_sel.get("ragas_metrics") or {}

    # Header card
    with st.container(border=True):
        st.markdown(f"**Question:** {sel_row.get('question', '')}")
        st.markdown(
            _badge(f"feature: {sel_row.get('demonstrates_feature', '?')}", "purple")
            + " "
            + _badge(f"intent: {sel_row.get('intent', '?')}", "blue")
            + " "
            + _badge(f"status: {_row_status(sel_row)}", "green"),
            unsafe_allow_html=True,
        )

    # Score cards (latest vs previous)
    s1, s2, s3, s4 = st.columns(4)
    def _metric_card(col, label, key):
        curr = ragas.get(key)
        prev = prev_ragas.get(key) if prev_data else None
        if isinstance(curr, (int, float)):
            delta = None
            if isinstance(prev, (int, float)):
                delta = f"{curr - prev:+.2f} vs prev"
            col.metric(label, f"{curr:.2f}", delta=delta)
        else:
            col.metric(label, "—")
    _metric_card(s1, "Faithfulness", "faithfulness")
    _metric_card(s2, "Ctx Precision", "context_precision")
    _metric_card(s3, "Ctx Recall", "context_recall")
    _metric_card(s4, "Ans Relevancy", "answer_relevancy")

    # Tabs for inspection
    tabs = st.tabs(["📝 Answer", "📚 Retrieved Contexts", "🎯 Sources & Keywords", "🧾 Raw JSON"])

    with tabs[0]:
        if prev_data:
            ca, cb = st.columns(2)
            with ca:
                st.markdown("**Latest answer**")
                st.write(sel_row.get("answer", "") or "_(empty)_")
            with cb:
                st.markdown("**Previous answer**")
                st.write(prev_sel.get("answer", "") or "_(empty)_")
        else:
            st.write(sel_row.get("answer", "") or "_(empty)_")

    with tabs[1]:
        contexts = sel_row.get("contexts", []) or []
        if not contexts:
            st.caption("No retrieved contexts captured.")
        else:
            for i, ctx in enumerate(contexts, 1):
                with st.expander(f"Context #{i}", expanded=(i == 1)):
                    st.write(ctx)

    with tabs[2]:
        gold_sources = sel_row.get("golden_sources", []) or []
        actual_sources = sel_row.get("actual_sources", []) or []
        overlap = sel_row.get("source_overlap", {}) or {}
        keywords = sel_row.get("forbidden_keywords", []) or []
        forbidden = sel_row.get("forbidden_check", {}) or {}

        cA, cB = st.columns(2)
        with cA:
            st.markdown("**Golden sources (expected)**")
            for s in gold_sources:
                st.markdown(f"- `{s}`")
            if not gold_sources:
                st.caption("none")
        with cB:
            st.markdown("**Actual sources (retrieved)**")
            for s in actual_sources:
                st.markdown(f"- `{s}`")
            if not actual_sources:
                st.caption("none")

        st.markdown("**Source overlap**")
        st.json(overlap)

        if keywords:
            st.markdown("**Forbidden keyword check**")
            st.json(forbidden)

    with tabs[3]:
        st.json(sel_row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="Sahakar Sahayak — Cooperative & Scheme Assistant",
        page_icon="🤝",
        layout="centered",
        initial_sidebar_state="auto",  # open on desktop, closed on phones

    )
    st.markdown(_CSS, unsafe_allow_html=True)

    st.session_state.setdefault("base_url_input", f"http://localhost:{settings.api_host_port}")
    base_url = st.session_state["base_url_input"]
    info = detect_api_features(base_url)
    query_settings = _sidebar(info)
    base_url = st.session_state["base_url_input"]

    if not st.session_state.get("token"):
        _sign_in_screen(base_url)
        return

    # Upload and SQL approval stay hidden unless enabled in config; the old golden-set dashboard
    # only appears when eval/results/*.json exists (this project's results are in results/*.csv)
    extra = []
    if settings.ui_upload_enabled:
        extra.append(("Upload", lambda: _upload_section(base_url)))
    if settings.sql_enabled:
        extra.append(("SQL approval", lambda: _sql_approval_section(base_url)))
    if _list_eval_files():
        extra.append(("Evaluation results", _eval_dashboard_section))

    if not extra:
        _chat_section(base_url, query_settings)
        return
    tabs = st.tabs(["Ask"] + [name for name, _ in extra])
    with tabs[0]:
        _chat_section(base_url, query_settings)
    for tab, (_, render) in zip(tabs[1:], extra, strict=True):
        with tab:
            render()


if __name__ == "__main__":
    main()

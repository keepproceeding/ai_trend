import os
import re
import html
import json
import time
from datetime import datetime, timedelta
import requests
import feedparser
from google import genai
from google.genai import errors as genai_errors

MAX_TELEGRAM_LENGTH = 4096
RECENT_DAYS = 2
REQUEST_TIMEOUT = 30

RSS_FEEDS = [
    ("business", "OpenAI", "https://openai.com/news/rss.xml"),
    ("business", "Anthropic", "https://www.anthropic.com/news/rss.xml"),
    ("business", "Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("business", "Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("technical", "LangChain", "https://blog.langchain.dev/rss/"),
    ("technical", "LangGraph", "https://blog.langchain.dev/rss/"),
    ("technical", "LlamaIndex", "https://www.llamaindex.ai/blog/rss.xml"),
    ("community", "Reddit r/localLLaMA", "https://www.reddit.com/r/localLLaMA/top.rss?t=day"),
    ("community", "Reddit r/ClaudeAI", "https://www.reddit.com/r/ClaudeAI/top.rss?t=day"),
]

GOOGLE_NEWS_RSS_FEEDS = [
    (
        "business",
        "Google News RSS",
        "https://news.google.com/rss/search?q=((OpenAI+OR+Anthropic+OR+Google+DeepMind+OR+Mistral)+AND+(announced+OR+launch+OR+launched+OR+released+OR+debuted+OR+unveiled))+when:7d&hl=en-US&gl=US&ceid=US:en",
    ),
    (
        "business",
        "Google News RSS",
        "https://news.google.com/rss/search?q=((GPT+OR+Claude+OR+Gemini+OR+Llama+OR+Mistral)+AND+(API+update+OR+model+update+OR+preview+OR+GA+OR+general+availability+OR+release+notes))+when:7d&hl=en-US&gl=US&ceid=US:en",
    ),
    (
        "technical",
        "Google News RSS",
        "https://news.google.com/rss/search?q=((LangChain+OR+LangGraph+OR+LlamaIndex+OR+AutoGen+OR+CrewAI+OR+DSPy+OR+vLLM+OR+Ollama)+AND+(feature+OR+capability+OR+evaluation+OR+benchmark+OR+agent+OR+release+OR+released+OR+launch+OR+%22release+notes%22))+when:7d&hl=en-US&gl=US&ceid=US:en",
    ),
]

GITHUB_RELEASE_REPOS = [
    ("technical", "langchain-ai/langchain"),
    ("technical", "langchain-ai/langgraph"),
    ("technical", "run-llama/llama_index"),
    ("technical", "microsoft/autogen"),
    ("technical", "crewAIInc/crewAI"),
    ("technical", "stanfordnlp/dspy"),
    ("technical", "vllm-project/vllm"),
    ("technical", "ollama/ollama"),
]

HF_PAPERS_API = "https://huggingface.co/api/daily_papers"
HF_PAPERS_MIN_UPVOTES = 10  # 커뮤니티 upvote 최소 기준

RESEARCH_TOPIC_KEYWORDS = {
    # RAG / Retrieval
    "rag", "retrieval-augmented", "retrieval augmented", "dense retrieval",
    "hybrid retrieval", "reranking", "re-ranking", "graphrag", "graph rag",
    "contextual retrieval", "chunk", "indexing strategy",
    # KV Cache / Memory
    "kv cache", "key-value cache", "kv compression", "attention cache",
    "memory efficiency", "memory efficient", "memory optimization",
    "context compression", "prompt compression", "token compression",
    # TTFT / Inference Latency
    "ttft", "time to first token", "prefill", "prefill latency",
    "speculative decoding", "inference latency", "inference throughput",
    "decode latency", "serving latency",
    # Agent Loop / Harness Engineering
    "agentic", "multi-agent", "tool use", "tool calling",
    "reasoning loop", "self-correction", "self-reflection", "self-repair",
    "chain-of-thought", "chain of thought", "react framework",
    "agent harness", "evaluation harness", "agent scaffold",
    "loop engineering", "trajectory optimization",
    # Agent Evaluation / Benchmark
    "agent benchmark", "agent evaluation", "agent accuracy",
    "tool-use benchmark", "task completion",
    # General Optimization
    "flash attention", "long context", "rope scaling",
    "quantization", "pruning", "distillation", "sparsity",
}

SOURCE_PRIORITY = {
    "OpenAI": 0,
    "Anthropic": 0,
    "Google DeepMind": 0,
    "Hugging Face": 0,
    "LangChain": 0,
    "LangGraph": 0,
    "LlamaIndex": 0,
}

NOISY_DOMAINS = {
    "instagram.com",
    "www.instagram.com",
    "tiktok.com",
    "www.tiktok.com",
    "pinterest.com",
    "www.pinterest.com",
}

LOW_SIGNAL_TITLE_KEYWORDS = {
    "state of",
    "top ",
    "ai 50",
    "list",
    "predictions",
    "trends",
    "outlook",
    "roundup",
}

HIGH_SIGNAL_KEYWORDS = {
    "announce",
    "announced",
    "launch",
    "launched",
    "release",
    "released",
    "open-source",
    "open sourced",
    "ga",
    "general availability",
    "beta",
    "preview",
    "changelog",
    "release notes",
    "version",
    "v1",
    "v2",
    "v3",
    "api update",
    "new model",
    "new feature",
    "new capability",
    "agent",
    "evaluation",
    "benchmark",
    "observability",
    "tool calling",
    "workflow",
    "introduced",
    "introduces",
    "introducing",
}

LOW_SIGNAL_TECHNICAL_KEYWORDS = {
    "bug fix",
    "bugfix",
    "fixes",
    "minor fix",
    "patch release",
    "dependency bump",
    "version bump",
    "typo",
    "docs only",
    "internal cleanup",
    "refactor",
}

HIGH_SIGNAL_TECHNICAL_KEYWORDS = {
    "new feature",
    "feature",
    "capability",
    "agent",
    "evaluation",
    "eval",
    "benchmark",
    "observability",
    "tool calling",
    "workflow",
    "runtime",
    "sdk",
    "framework",
    "library",
    "launch",
    "release notes",
    "open-source",
}

# 1. 환경 변수 세팅
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')  # genai.Client()가 자동으로 인식하지만 명시적으로도 가져옵니다.
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')

# 2. 클라이언트 초기화
client = genai.Client(api_key=GEMINI_API_KEY)


def is_noisy_domain(url):
    if not url:
        return True
    lowered = url.lower()
    return any(domain in lowered for domain in NOISY_DOMAINS)


def is_pinpoint_update(title, content):
    text = f"{title or ''} {content or ''}".lower()
    has_high_signal = any(keyword in text for keyword in HIGH_SIGNAL_KEYWORDS)
    has_low_signal = any(keyword in (title or "").lower() for keyword in LOW_SIGNAL_TITLE_KEYWORDS)
    return has_high_signal and not has_low_signal


def is_major_technical_update(title, content):
    text = f"{title or ''} {content or ''}".lower()
    has_high_signal = any(keyword in text for keyword in HIGH_SIGNAL_TECHNICAL_KEYWORDS)
    has_low_signal = any(keyword in text for keyword in LOW_SIGNAL_TECHNICAL_KEYWORDS)
    return has_high_signal and not has_low_signal


def is_hot_research_paper(title, summary):
    text = f"{title or ''} {summary or ''}".lower()
    return any(keyword in text for keyword in RESEARCH_TOPIC_KEYWORDS)


def normalize_release_date(value):
    if not value:
        return "날짜 미상"

    text = str(value).strip()
    if not text:
        return "날짜 미상"

    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]

    return text


def is_recent_release_date(value):
    if not value or value == "날짜 미상":
        return False

    try:
        release_date = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return False

    today = datetime.now().date()
    earliest_allowed = today - timedelta(days=RECENT_DAYS)
    return earliest_allowed <= release_date <= today

def parse_datetime_to_date(value):
    if not value:
        return "날짜 미상"

    text = str(value).strip()
    if not text:
        return "날짜 미상"

    normalized = text.replace("Z", "+00:00")
    for parser in (
        lambda item: datetime.fromisoformat(item),
        lambda item: datetime.strptime(item[:10], "%Y-%m-%d"),
        lambda item: datetime.strptime(item, "%a, %d %b %Y %H:%M:%S %z"),
        lambda item: datetime.strptime(item, "%a, %d %b %Y %H:%M:%S GMT"),
    ):
        try:
            return parser(normalized).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return normalize_release_date(text)


def normalize_item(category, source, title, url, summary, release_date):
    normalized_date = normalize_release_date(release_date)
    cleaned_summary = re.sub(r"\s+", " ", str(summary or "")).strip()
    return {
        "category": category,
        "source": source,
        "title": str(title or "").strip(),
        "url": str(url or "").strip(),
        "summary": cleaned_summary,
        "release_date": normalized_date,
    }


def get_source_priority(source):
    if source in SOURCE_PRIORITY:
        return SOURCE_PRIORITY[source]
    if str(source).startswith("GitHub:"):
        return 1
    return 2


def normalize_title_key(title):
    lowered = str(title or "").lower()
    lowered = re.sub(r"https?://\S+", "", lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    lowered = re.sub(r"\b(introducing|introduces|announcing|announced|release|released|launch|launched|preview|general availability|ga)\b", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def get_release_date_sort_value(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return datetime.min


def collect_rss_news():
    items = []

    for category, source, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                release_date = parse_datetime_to_date(
                    entry.get("published") or entry.get("updated") or entry.get("pubDate")
                )
                url = entry.get("link", "")
                summary = entry.get("summary", "") or entry.get("description", "")

                item = normalize_item(
                    category=category,
                    source=source,
                    title=entry.get("title", ""),
                    url=url,
                    summary=summary,
                    release_date=release_date,
                )

                if not item["url"] or is_noisy_domain(item["url"]):
                    continue
                if not is_recent_release_date(item["release_date"]):
                    continue
                if not is_pinpoint_update(item["title"], item["summary"]):
                    continue
                if item["category"] == "technical" and not is_major_technical_update(item["title"], item["summary"]):
                    continue

                items.append(item)

            print(f"✅ RSS 수집 완료: {source}")
        except Exception as e:
            print(f"❌ RSS 수집 에러 ({source}): {e}")

    return items


def collect_google_news_rss():
    items = []

    for category, source, feed_url in GOOGLE_NEWS_RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                release_date = parse_datetime_to_date(
                    entry.get("published") or entry.get("updated") or entry.get("pubDate")
                )
                url = entry.get("link", "")
                summary = entry.get("summary", "") or entry.get("description", "")

                item = normalize_item(
                    category=category,
                    source=source,
                    title=entry.get("title", ""),
                    url=url,
                    summary=summary,
                    release_date=release_date,
                )

                if not item["url"] or is_noisy_domain(item["url"]):
                    continue
                if not is_recent_release_date(item["release_date"]):
                    continue
                if not is_pinpoint_update(item["title"], item["summary"]):
                    continue
                if item["category"] == "technical" and not is_major_technical_update(item["title"], item["summary"]):
                    continue

                items.append(item)

            print(f"✅ Google News RSS 수집 완료: {category}")
        except Exception as e:
            print(f"❌ Google News RSS 수집 에러 ({category}): {e}")

    return items


def collect_github_releases():
    items = []
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    for category, repo in GITHUB_RELEASE_REPOS:
        api_url = f"https://api.github.com/repos/{repo}/releases?per_page=5"
        try:
            response = requests.get(api_url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            for release in response.json():
                release_date = parse_datetime_to_date(release.get("published_at") or release.get("created_at"))
                summary = release.get("body", "") or release.get("name", "")

                item = normalize_item(
                    category=category,
                    source=f"GitHub:{repo}",
                    title=release.get("name") or release.get("tag_name") or repo,
                    url=release.get("html_url", ""),
                    summary=summary,
                    release_date=release_date,
                )

                if not item["url"] or is_noisy_domain(item["url"]):
                    continue
                if not is_recent_release_date(item["release_date"]):
                    continue
                if not is_pinpoint_update(item["title"], item["summary"]):
                    continue
                if item["category"] == "technical" and not is_major_technical_update(item["title"], item["summary"]):
                    continue

                items.append(item)

            print(f"✅ GitHub Releases 수집 완료: {repo}")
        except Exception as e:
            print(f"❌ GitHub Releases 수집 에러 ({repo}): {e}")

    return items


def format_news_items(items):
    collected_data = []
    seen_urls = set()
    seen_title_keys = set()

    sorted_items = sorted(
        items,
        key=lambda current: (
            get_release_date_sort_value(current["release_date"]),
            -get_source_priority(current["source"]),
        ),
        reverse=True,
    )

    for item in sorted_items:
        url = item["url"]
        title_key = normalize_title_key(item["title"])
        if url in seen_urls:
            continue
        if title_key and title_key in seen_title_keys:
            continue
        seen_urls.add(url)
        if title_key:
            seen_title_keys.add(title_key)
        collected_data.append(
            "\n".join(
                [
                    f"카테고리: {item['category']}",
                    f"출처: {item['source']}",
                    f"제목: {item['title']}",
                    f"릴리즈 날짜: {item['release_date']}",
                    f"링크: {item['url']}",
                    f"본문 요약: {item['summary']}",
                ]
            )
        )

    return "\n---\n".join(collected_data)


def collect_hf_papers():
    """HuggingFace Daily Papers에서 커뮤니티 upvote를 받은 논문을 수집합니다."""
    items = []
    try:
        response = requests.get(HF_PAPERS_API, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        papers = response.json()

        count = 0
        for entry in papers:
            paper = entry.get("paper", {})
            upvotes = paper.get("upvotes", 0)
            if upvotes < HF_PAPERS_MIN_UPVOTES:
                continue

            arxiv_id = paper.get("id", "")
            url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""
            title = paper.get("title", "")
            summary = paper.get("summary", "")
            published_at = paper.get("publishedAt", "")
            release_date = parse_datetime_to_date(published_at)

            item = normalize_item(
                category="research",
                source=f"HuggingFace Papers (👍{upvotes})",
                title=title,
                url=url,
                summary=summary,
                release_date=release_date,
            )

            if not item["url"]:
                continue
            if not is_hot_research_paper(item["title"], item["summary"]):
                continue

            items.append(item)
            count += 1

        print(f"✅ HuggingFace Papers 수집 완료 ({count}건, upvotes ≥ {HF_PAPERS_MIN_UPVOTES})")
    except Exception as e:
        print(f"❌ HuggingFace Papers 수집 에러: {e}")

    return items


def get_hybrid_news():
    """공식 RSS + GitHub Releases + Google News RSS + arXiv 논문을 조합해 수집합니다."""
    all_items = []
    all_items.extend(collect_rss_news())
    all_items.extend(collect_github_releases())
    all_items.extend(collect_google_news_rss())
    all_items.extend(collect_hf_papers())
    return format_news_items(all_items)

def generate_curation_report(news_data):
    """수집된 뉴스를 바탕으로 Gemini가 구조화된 JSON 리포트를 생성합니다."""

    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""
너는 기업의 AI 플랫폼 도입과 전략을 담당하는 시니어 AI Project PM 및 AI 엔지니어야.
아래는 공식 RSS, GitHub Releases, Google News RSS를 통해 수집된 데일리 AI/IT 발표, 이슈, 릴리즈, 업데이트 원문 데이터야.
이 내용들을 분석해서 반드시 JSON 객체 하나만 출력해.

[수집된 데이터]
{news_data}

[중요 규칙]
- 마크다운, HTML 태그, 코드블록 금지.
- 설명 문장 없이 JSON만 출력.
- 데이터가 부족하면 빈 배열 [] 사용.
- 기사 항목은 '발표/릴리즈/업데이트' 등 핀포인트 정보 위주로 선택.
- 입력 데이터에 있는 날짜만 사용하고, 모델이 제품의 과거 최초 출시일이나 임의 날짜를 추론해서 쓰면 안 됨.
- 각 기사에는 입력에 포함된 릴리즈 날짜를 그대로 넣고, 최근 {RECENT_DAYS}일 이내 항목만 사용.
- 날짜가 없거나 최근 {RECENT_DAYS}일을 벗어나는 항목은 JSON에 포함하지 말 것.
- 각 기사 설명은 '코멘트'가 아니라 핵심 요약 1줄(summary_one_line)만 작성.
- headline_summary, summary_one_line, agent_insight, market_pulse.reason 등 모든 텍스트 필드는 "~했습니다", "~입니다", "~됩니다" 등 서술형 종결 금지. "OO 출시", "OO 업데이트", "OO 지원 추가" 등 명사형으로 끝낼 것.
- 테크니컬 업데이트는 단순 버그 수정, 마이너 패치, 내부 리팩터링보다 새로운 기능, 에이전트 기능, 평가 방식, 벤치마크, 주요 라이브러리/서비스 업데이트를 우선 선택.
- LangChain뿐 아니라 LangGraph, 에이전트 오케스트레이션, 에이전트 평가/observability 관련 업데이트가 있으면 우선 반영.
- technical_updates에는 오픈소스 릴리즈 외에 HuggingFace Papers 커뮤니티 upvote를 받은 논문도 포함할 수 있음. RAG/RASG, KV 캐시 최적화, TTFT/추론 지연 개선, 메모리 효율화, 에이전트 루프 엔지니어링, 하네스 엔지니어링, 에이전트 정확도·성능 향상 관련 논문이 있으면 최대 2건까지 우선 선택. 논문 항목의 title에는 "[논문]" 접두어를 붙일 것.
- market_pulse 레벨 판정: 아래 조건을 모두 충족할 때만 "hot". 하나라도 빠지면 "quiet".
  (1) OpenAI, Anthropic, Google DeepMind, Meta 중 한 곳 이상이 주체일 것.
  (2) 완전히 새로운 frontier 모델 출시(예: GPT-5, Claude 4, Gemini 3 등 신규 시리즈) OR 산업 전반에 즉각적 영향을 주는 플랫폼급 발표일 것.
  (3) 단순 API 업데이트, 기존 모델 마이너 버전, 가격 변경, 오픈소스 릴리즈, 연구 논문, 기능 추가, 툴 출시는 아무리 주목받아도 "hot" 불가. 반드시 "quiet".
- agent_insight에는 오늘 동향이 "hot"인지 "quiet"인지와 그 판단 이유를 함께 포함.

[JSON 스키마]
{{{{
  "date": "{today}",
  "headline_summary": ["핵심내용1", "핵심내용2"],
    "market_pulse": {{
        "level": "hot 또는 quiet",
        "reason": "판단 근거 1문장"
    }},
  "business_updates": [
        {{"title": "", "release_date": "YYYY-MM-DD 또는 날짜 미상", "url": "", "summary_one_line": ""}}
  ],
  "technical_updates": [
        {{"title": "", "release_date": "YYYY-MM-DD 또는 날짜 미상", "url": "", "summary_one_line": ""}}
  ],
  "agent_insight": ["핵심인사이트 1문장"]
}}}}
"""

    max_retries = 4
    base_delay = 30  # seconds

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            return response.text
        except genai_errors.ServerError as e:
            if e.status_code == 503 and attempt < max_retries - 1:
                wait = base_delay * (2 ** attempt)
                print(f"⚠️ Gemini 503 과부하, {wait}초 후 재시도 ({attempt + 1}/{max_retries - 1})...")
                time.sleep(wait)
            else:
                raise


def extract_json_object(text):
    """모델 응답에서 JSON 객체를 안전하게 추출합니다."""
    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")

    if first_brace == -1 or last_brace == -1 or first_brace >= last_brace:
        raise ValueError("Gemini 응답에서 JSON 객체를 찾지 못했습니다.")

    json_text = cleaned[first_brace:last_brace + 1]
    return json.loads(json_text)


def build_html_report(report):
    """구조화된 리포트 JSON을 Telegram 안전 HTML 메시지로 렌더링합니다."""
    # 모델이 날짜를 임의로 바꾸지 않도록 실행 시점의 날짜를 강제 사용
    date = html.escape(datetime.now().strftime("%Y-%m-%d"))
    summary = report.get("headline_summary", []) or []
    market_pulse = report.get("market_pulse", {}) or {}
    business = report.get("business_updates", []) or []
    technical = report.get("technical_updates", []) or []
    insights = report.get("agent_insight", []) or []

    lines = [
        f"<b>📰 AI 테크 데일리 | {date}</b>",
    ]

    # 시장 온도 먼저 표시
    pulse_raw = str(market_pulse.get("level", "unknown")).strip().lower()
    pulse_emoji = "🔥" if pulse_raw == "hot" else "🌿" if pulse_raw == "quiet" else "📊"
    pulse_level = html.escape(str(market_pulse.get("level", "unknown")))
    pulse_reason = html.escape(str(market_pulse.get("reason", "판단 근거 없음")))
    lines.append(f"<b>온도: {pulse_emoji} {pulse_level}</b> | {pulse_reason}")
    lines.append("")

    # 핵심 요약 (축약)
    if summary:
        lines.append("<b>🔥 핵심 요약</b>")
        for item in summary[:2]:
            lines.append(f"• {html.escape(str(item))}")
        lines.append("")
    else:
        lines.append("<i>오늘은 주요 발표/릴리즈가 제한적입니다.</i>")
        lines.append("")

    # 비즈니스 업데이트 (축약)
    if business:
        lines.append("<b>📈 AI 플랫폼 업데이트</b>")
        for item in business[:4]:
            title = html.escape(str(item.get("title", "제목 없음")))
            release_date = html.escape(str(item.get("release_date", "날짜 미상")))
            url = str(item.get("url", "")).strip()
            summary_one_line = html.escape(str(item.get("summary_one_line", "")))

            if url.startswith("http://") or url.startswith("https://"):
                safe_url = html.escape(url, quote=True)
                lines.append(f"• <a href=\"{safe_url}\">{title}</a> <i>({release_date})</i>")
            else:
                lines.append(f"• {title} <i>({release_date})</i>")
            if summary_one_line:
                lines.append(f"  └ {summary_one_line}")
        lines.append("")

    # 테크니컬 업데이트 (축약)
    if technical:
        lines.append("<b>🛠️ 오픈소스 & 기술 업데이트</b>")
        for item in technical[:4]:
            title = html.escape(str(item.get("title", "제목 없음")))
            release_date = html.escape(str(item.get("release_date", "날짜 미상")))
            url = str(item.get("url", "")).strip()
            summary_one_line = html.escape(str(item.get("summary_one_line", "")))

            if url.startswith("http://") or url.startswith("https://"):
                safe_url = html.escape(url, quote=True)
                lines.append(f"• <a href=\"{safe_url}\">{title}</a> <i>({release_date})</i>")
            else:
                lines.append(f"• {title} <i>({release_date})</i>")
            if summary_one_line:
                lines.append(f"  └ {summary_one_line}")
        lines.append("")

    # 인사이트 (한 줄)
    lines.append("<b>💡 인사이트</b>")
    if insights:
        lines.append(html.escape(str(insights[0])))
    else:
        lines.append("<i>세부 인사이트는 추후 업데이트 예정입니다.</i>")

    # HTML parse_mode에서도 줄바꿈(\n)이 렌더링되므로 분할 안정성을 위해 실제 줄바꿈을 사용
    return "\n".join(lines).strip()

def send_telegram_message(text):
    """텔레그램으로 HTML 포맷의 메시지를 전송합니다."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    def normalize_html_message(value):
        normalized = value.replace("\r\n", "\n")
        normalized = normalized.replace("<br/>", "<br>").replace("<br />", "<br>")
        return normalized

    def split_message_by_lines(value, max_length):
        lines = value.split("\n")
        chunks = []
        current = ""

        for line in lines:
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) <= max_length:
                current = candidate
                continue

            if current:
                chunks.append(current)

            # 단일 라인이 너무 긴 경우 강제로 쪼개되, 가능한 태그 경계 근처에서 분할
            while len(line) > max_length:
                split_at = line.rfind(" ", 0, max_length)
                if split_at == -1:
                    split_at = max_length
                chunks.append(line[:split_at])
                line = line[split_at:].lstrip()

            current = line

        if current:
            chunks.append(current)

        return chunks

    def strip_html_tags(value):
        text_with_newlines = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
        text_only = re.sub(r"<[^>]+>", "", text_with_newlines)
        return html.unescape(text_only)

    safe_text = normalize_html_message(text)
    chunks = split_message_by_lines(safe_text, MAX_TELEGRAM_LENGTH)

    for chunk in chunks:
        payload = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        response = requests.post(url, json=payload)

        # HTML 파싱 실패(400) 시 태그를 제거한 일반 텍스트로 재시도
        if response.status_code == 400:
            print(f"⚠️ Telegram HTML 전송 실패, fallback 적용: {response.text}")
            fallback_payload = {
                "chat_id": CHAT_ID,
                "text": strip_html_tags(chunk),
                "disable_web_page_preview": False,
            }
            fallback_response = requests.post(url, json=fallback_payload)
            fallback_response.raise_for_status()
            continue

        response.raise_for_status()

if __name__ == "__main__":
    print("1. 공식 RSS + GitHub Releases + Google News RSS 수집 시작...")
    raw_news = get_hybrid_news()
    
    if not raw_news.strip():
        print("수집된 뉴스가 없습니다. 프로세스를 종료합니다.")
        exit()
        
    print("2. Gemini 요약 리포트 생성 중...")
    raw_model_output = generate_curation_report(raw_news)

    try:
        report_json = extract_json_object(raw_model_output)
        curated_message = build_html_report(report_json)
    except Exception as e:
        print(f"⚠️ JSON 파싱 실패, 원문 텍스트 fallback 사용: {e}")
        curated_message = raw_model_output
    
    print("3. 텔레그램 전송 중...")
    send_telegram_message(curated_message)
    print("✅ 모든 파이프라인 정상 완료!")
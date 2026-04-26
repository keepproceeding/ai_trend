import os
import re
import html
import json
from datetime import datetime, timedelta
import requests
from google import genai
from tavily import TavilyClient

MAX_TELEGRAM_LENGTH = 4096
RECENT_DAYS = 7

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
    "introduced",
    "introduces",
    "introducing",
}

# 1. 환경 변수 세팅
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')  # genai.Client()가 자동으로 인식하지만 명시적으로도 가져옵니다.

# 2. 클라이언트 초기화
client = genai.Client(api_key=GEMINI_API_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY)


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

def get_tavily_news():
    """Tavily API를 활용하여 최근 7일의 '발표/릴리즈/업데이트' 중심 뉴스만 수집합니다."""

    # 두루뭉술한 거시 트렌드 대신 '오늘 공개/발표/업데이트' 중심 쿼리로 제한
    query_configs = [
        {
            "query": "AI companies announced today new model release OR API update OR product launch OR GA OR preview",
            "include_domains": [
                "openai.com",
                "anthropic.com",
                "blog.google",
                "deepmind.google",
                "mistral.ai",
                "ai.meta.com",
                "huggingface.co",
                "cohere.com",
                "stability.ai",
            ],
        },
        {
            "query": "GitHub release notes today LangChain LlamaIndex AutoGen CrewAI DSPy open source AI agent framework",
            "include_domains": [
                "github.com",
                "docs.langchain.com",
                "llamaindex.ai",
                "microsoft.github.io",
            ],
        },
        {
            "query": "AI infra update today CUDA vLLM Ollama Ray Weights & Biases launch release notes",
            "include_domains": [
                "developer.nvidia.com",
                "github.com",
                "vllm.ai",
                "ollama.com",
                "wandb.ai",
                "ray.io",
            ],
        },
    ]
    
    collected_data = []
    seen_urls = set()
    
    for config in query_configs:
        q = config["query"]
        try:
            response = tavily.search(
                query=q,
                search_depth="advanced",
                topic="news",
                days=RECENT_DAYS,
                max_results=8,
                include_domains=config["include_domains"],
            )
            
            for result in response.get('results', []):
                title = result.get('title')
                url = result.get('url')
                content = result.get('content')
                release_date = normalize_release_date(
                    result.get('published_date') or result.get('published_at') or result.get('date')
                )

                if not url or url in seen_urls:
                    continue
                if is_noisy_domain(url):
                    continue
                if not is_pinpoint_update(title, content):
                    continue
                if not is_recent_release_date(release_date):
                    continue

                seen_urls.add(url)
                collected_data.append(
                    f"제목: {title}\n릴리즈 날짜: {release_date}\n링크: {url}\n본문 요약: {content}\n"
                )
                
            print(f"✅ Tavily 검색 완료: '{q}'")
        except Exception as e:
            print(f"❌ Tavily 검색 에러 ({q}): {e}")
            
    return "\n---\n".join(collected_data)

def generate_curation_report(news_data):
    """수집된 뉴스를 바탕으로 Gemini가 구조화된 JSON 리포트를 생성합니다."""

    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""
너는 기업의 AI 플랫폼 도입과 전략을 담당하는 시니어 AI Project PM 및 AI 엔지니어야.
아래는 Tavily 검색엔진을 통해 수집된 데일리 AI/IT 발표,이슈,릴리즈,업데이트 원문 데이터야.
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
- agent_insight에는 오늘 동향이 "hot"인지 "quiet"인지와 그 판단 이유를 함께 포함.

[JSON 스키마]
{{
  "date": "{today}",
  "headline_summary": ["문장1", "문장2"],
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
  "agent_insight": ["문단1", "문단2"]
}}
"""

    response = client.models.generate_content(
        model='gemini-2.5-flash', 
        contents=prompt,
    )
    return response.text


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
        "",
        "<b>🔥 오늘의 AI 핵심 요약</b>",
    ]

    if summary:
        for item in summary[:3]:
            lines.append(f"• {html.escape(str(item))}")
    else:
        lines.append("• 오늘은 유의미한 핀포인트 업데이트가 제한적입니다.")

    lines.extend(["", "<b>📈 1. AI 비즈니스 & 플랫폼 발표, 이슈, 업데이트 사항</b>"])

    if business:
        for item in business[:6]:
            title = html.escape(str(item.get("title", "제목 없음")))
            release_date = html.escape(str(item.get("release_date", "날짜 미상")))
            url = str(item.get("url", "")).strip()
            summary_one_line = html.escape(str(item.get("summary_one_line", "핵심 요약 없음")))

            if url.startswith("http://") or url.startswith("https://"):
                safe_url = html.escape(url, quote=True)
                lines.append(f"• <a href=\"{safe_url}\">{title}</a>")
            else:
                lines.append(f"• {title}")
            lines.append(f"└ 릴리즈 날짜: {release_date}")
            lines.append(f"└ 핵심 요약: {summary_one_line}")
            lines.append("")
    else:
        lines.append("• 수집된 비즈니스 업데이트가 없습니다.")

    lines.extend(["", "<b>🛠️ 2. 테크니컬 이슈 & 오픈소스 발표, 이슈, 업데이트 사항</b>"])

    if technical:
        for item in technical[:6]:
            title = html.escape(str(item.get("title", "제목 없음")))
            release_date = html.escape(str(item.get("release_date", "날짜 미상")))
            url = str(item.get("url", "")).strip()
            summary_one_line = html.escape(str(item.get("summary_one_line", "핵심 요약 없음")))

            if url.startswith("http://") or url.startswith("https://"):
                safe_url = html.escape(url, quote=True)
                lines.append(f"• <a href=\"{safe_url}\">{title}</a>")
            else:
                lines.append(f"• {title}")
            lines.append(f"└ 릴리즈 날짜: {release_date}")
            lines.append(f"└ 핵심 요약: {summary_one_line}")
            lines.append("")
    else:
        lines.append("• 수집된 테크니컬 업데이트가 없습니다.")

    lines.extend(["", "<b>💡 에이전트의 인사이트</b>"])
    pulse_level = html.escape(str(market_pulse.get("level", "unknown")))
    pulse_reason = html.escape(str(market_pulse.get("reason", "판단 근거 없음")))
    lines.append(f"• 오늘의 온도: {pulse_level}")
    lines.append(f"• 판단 근거: {pulse_reason}")
    lines.append("")
    if insights:
        for paragraph in insights[:2]:
            lines.append(html.escape(str(paragraph)))
            lines.append("")
    else:
        lines.append("오늘은 발표/릴리즈 중심으로 추적된 업데이트를 바탕으로 제한된 인사이트만 도출되었습니다.")

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
    print("1. Tavily AI 뉴스 검색 시작...")
    raw_news = get_tavily_news()
    
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
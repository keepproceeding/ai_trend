import os
import requests
from google import genai
from tavily import TavilyClient

MAX_TELEGRAM_LENGTH = 4096

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

def get_tavily_news():
    """Tavily API를 활용하여 최근 24시간의 '발표/릴리즈/업데이트' 중심 뉴스를 수집합니다."""

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
                days=1,
                max_results=8,
                include_domains=config["include_domains"],
            )
            
            for result in response.get('results', []):
                title = result.get('title')
                url = result.get('url')
                content = result.get('content')

                if not url or url in seen_urls:
                    continue
                if is_noisy_domain(url):
                    continue
                if not is_pinpoint_update(title, content):
                    continue

                seen_urls.add(url)
                collected_data.append(f"제목: {title}\n링크: {url}\n본문 요약: {content}\n")
                
            print(f"✅ Tavily 검색 완료: '{q}'")
        except Exception as e:
            print(f"❌ Tavily 검색 에러 ({q}): {e}")
            
    return "\n---\n".join(collected_data)

def generate_curation_report(news_data):
    """수집된 뉴스를 바탕으로 Gemini 1.5 Flash가 리포트를 작성합니다."""
    
    prompt = f"""
    너는 기업의 AI 플랫폼 도입과 전략을 담당하는 시니어 AI Project PM이야.
    아래는 오늘 Tavily AI 검색엔진을 통해 수집된 데일리 AI/IT 트렌드 원문 데이터야.
    이 내용들을 분석해서 텔레그램 메신저에 맞게 가독성 좋은 보고서를 작성해줘.

    [수집된 데이터]
    {news_data}

        [출력 템플릿 규정]
        - 반드시 한국어로 작성.
        - 텔레그램 HTML parse_mode에 맞는 태그만 사용: <b>, <i>, <a>, <code>, <br>
        - 마크다운 문법(**, __, [], ())은 절대 사용하지 말 것.
        - 섹션 제목은 <b>태그</b>로 강조하고, 섹션 사이에는 빈 줄 1개를 둘 것.
        - 각 기사 항목은 아래 형식으로 작성:
            • <a href="기사링크">기사 제목</a><br>
                └ 코멘트: 한 줄 요약

        [출력 예시 형식]
        <b>🔥 오늘의 AI 핵심 요약</b><br>
        핵심 요약 2~3줄<br>
        <br>
        <b>📈 1. AI 비즈니스 & 플랫폼 트렌드</b><br>
        • <a href="https://example.com">기사 제목</a><br>
        └ 코멘트: PM 관점의 전략적 의미 1줄<br>
        <br>
        <b>🛠️ 2. 테크니컬 이슈 & 오픈소스 동향</b><br>
        • <a href="https://example.com">기사 제목</a><br>
        └ 코멘트: 엔지니어링 시사점 1줄<br>
        <br>
        <b>💡 에이전트의 인사이트</b><br>
        오늘의 동향 종합 인사이트 1~2문단
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash', 
        contents=prompt,
    )
    return response.text

def send_telegram_message(text):
    """텔레그램으로 HTML 포맷의 메시지를 전송합니다."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # Telegram은 메시지 길이 제한(4096자)이 있어 안전하게 분할 전송합니다.
    chunks = [text[i:i + MAX_TELEGRAM_LENGTH] for i in range(0, len(text), MAX_TELEGRAM_LENGTH)]

    for chunk in chunks:
        payload = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()

if __name__ == "__main__":
    print("1. Tavily AI 뉴스 검색 시작...")
    raw_news = get_tavily_news()
    
    if not raw_news.strip():
        print("수집된 뉴스가 없습니다. 프로세스를 종료합니다.")
        exit()
        
    print("2. Gemini 요약 리포트 생성 중...")
    curated_message = generate_curation_report(raw_news)
    
    print("3. 텔레그램 전송 중...")
    send_telegram_message(curated_message)
    print("✅ 모든 파이프라인 정상 완료!")
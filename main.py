import os
import requests
import feedparser
from google import genai

# 1. 환경 변수 세팅 (GitHub Secrets에서 가져옴)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
# 주의: GEMINI_API_KEY는 os.environ에 등록되어 있으면 genai.Client()가 자동으로 읽어옵니다.

# 2. 최신 SDK 클라이언트 초기화
client = genai.Client()

def get_rss_news():
    """커뮤니티 RSS 피드에서 최신 트렌드를 수집합니다."""
    feeds = {
        "HuggingFace Papers": "https://huggingface.co/papers.rss",
        "Reddit LocalLLaMA": "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day",
        "Reddit LangChain": "https://www.reddit.com/r/LangChain/top/.rss?t=day",
        "LangChain Blog": "https://blog.langchain.dev/rss/"
    }
    
    collected_news = []
    
    for source, url in feeds.items():
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            feed = feedparser.parse(response.content)
            
            # 소스별 상위 3개 기사만 추출
            for entry in feed.entries[:3]:
                title = entry.title
                link = entry.link
                collected_news.append(f"[{source}] {title}\nLink: {link}")
        except Exception as e:
            print(f"[{source}] RSS 수집 에러: {e}")
            continue
            
    return "\n\n".join(collected_news)

def generate_curation_report(news_data):
    """수집된 뉴스를 바탕으로 최신 Gemini API를 호출하여 리포트를 작성합니다."""
    
    prompt = f"""
    너는 기업의 AI 플랫폼 도입과 전략을 담당하는 시니어 AI Project PM이야.
    아래는 오늘 수집된 AI 커뮤니티(HuggingFace, Reddit, LangChain 등)의 최신 트렌드와 뉴스들이야.
    이 내용들을 분석해서 텔레그램 메신저에 맞게 가독성 좋은 보고서를 작성해줘.

    [수집된 뉴스 데이터]
    {news_data}

    [출력 템플릿 규정] - 반드시 아래 형식을 지켜서 한국어로 작성할 것 (마크다운 굵기 표현 ** 사용 가능)
    
    🔥 **[오늘의 AI 핵심 요약]**
    - (전체 뉴스를 관통하는 가장 중요한 트렌드 2~3줄 요약)

    📈 **[1. AI 트렌드 동향]**
    - [기사 제목](기사 링크)
      └ 💬 코멘트: (PM 관점에서의 비즈니스/트렌드 의미 1줄)
    - [기사 제목](기사 링크)
      └ 💬 코멘트: (내용...)

    🛠️ **[2. AI, IT 테크니컬 업데이트 사항]**
    - [기사 제목](기사 링크)
      └ 💬 코멘트: (엔지니어링/기술적 한계점이나 돌파구 1줄)
    - [기사 제목](기사 링크)
      └ 💬 코멘트: (내용...)

    💡 **[PM의 시선 (인사이트)]**
    - (오늘의 동향을 종합했을 때, 향후 AI 플랫폼 기획 및 인프라 도입 시 고려해야 할 점이나 너의 통찰력 있는 생각 1~2문단)
    """
    
    # 🌟 최신 SDK의 generate_content 호출 방식
    response = client.models.generate_content(
        model='gemini-1.5-flash', 
        contents=prompt,
    )
    
    return response.text

def send_telegram_message(text):
    """텔레그램으로 마크다운 포맷의 메시지를 전송합니다."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": text, 
        "parse_mode": "Markdown" 
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()

if __name__ == "__main__":
    print("1. RSS 뉴스 수집 시작...")
    raw_news = get_rss_news()
    
    if not raw_news.strip():
        print("수집된 뉴스가 없습니다. 프로세스를 종료합니다.")
        exit()
        
    print("2. LLM 요약 리포트 생성 중...")
    curated_message = generate_curation_report(raw_news)
    
    print("3. 텔레그램 전송 중...")
    send_telegram_message(curated_message)
    print("✅ 완료!")
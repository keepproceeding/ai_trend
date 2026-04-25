import os
import requests
from google import genai
from tavily import TavilyClient

# 1. 환경 변수 세팅
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')  # genai.Client()가 자동으로 인식하지만 명시적으로도 가져옵니다.

# 2. 클라이언트 초기화
client = genai.Client(api_key=GEMINI_API_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY)

def get_tavily_news():
    """Tavily API를 활용하여 최근 24시간 내의 고품질 AI/IT 트렌드를 검색합니다."""
    
    # PM 관점의 비즈니스 트렌드와 엔지니어링 딥다이브를 모두 커버하는 두 가지 쿼리
    queries = [
        "What are the most important AI enterprise trends, LLM releases, and tech business news today?",
        "Latest updates, releases, or trending discussions regarding LangChain, Agentic RAG, and LocalLLaMA."
    ]
    
    collected_data = []
    
    for q in queries:
        try:
            # search_depth="advanced": 심층 검색
            # time_range="day": 최근 24시간 내의 문서만 필터링 (가장 중요한 옵션)
            response = tavily.search(query=q, search_depth="advanced", time_range="day", max_results=4)
            
            for result in response.get('results', []):
                title = result.get('title')
                url = result.get('url')
                content = result.get('content') # 사이트 본문의 핵심 요약 텍스트
                collected_data.append(f"제목: {title}\n링크: {url}\n본문 요약: {content}\n")
                
            print(f"✅ Tavily 검색 완료: '{q}'")
        except Exception as e:
            print(f"❌ Tavily 검색 에러 ({q}): {e}")
            
    return "\n---\n".join(collected_data)

def generate_curation_report(news_data):
    """수집된 뉴스를 바탕으로 Gemini 1.5 Flash가 리포트를 작성합니다."""
    
    prompt = f"""
    너는 기업의 AI 플랫폼 도입과 전략을 담당하는 시니어 AI Project PM이야.
    아래는 오늘 Tavily AI 검색엔진을 통해 수집된 최신 AI/IT 트렌드 원문 데이터야.
    이 내용들을 분석해서 텔레그램 메신저에 맞게 가독성 좋은 보고서를 작성해줘.

    [수집된 데이터]
    {news_data}

    [출력 템플릿 규정] - 반드시 아래 형식을 지켜서 한국어로 작성할 것
    
    🔥 **[오늘의 AI 핵심 요약]**
    - (전체 뉴스를 관통하는 가장 중요한 트렌드 2~3줄 요약)

    📈 **[1. AI 비즈니스 & 플랫폼 트렌드]**
    - [기사 제목](기사 링크)
      └ 💬 코멘트: (PM 관점에서의 비즈니스/플랫폼 전략적 의미 1줄)
    - [기사 제목](기사 링크)
      └ 💬 코멘트: (내용...)

    🛠️ **[2. 테크니컬 이슈 & 오픈소스 동향]**
    - [기사 제목](기사 링크)
      └ 💬 코멘트: (엔지니어링/기술적 시사점 1줄)
    - [기사 제목](기사 링크)
      └ 💬 코멘트: (내용...)

    💡 **[에이전트의 인사이트]**
    - (오늘의 동향을 종합했을 때, 향후 하이브리드(On-prem/Cloud) AI 플랫폼 기획 및 인프라 도입 시 고려해야 할 점이나 너의 통찰력 있는 생각 1~2문단)
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash', 
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
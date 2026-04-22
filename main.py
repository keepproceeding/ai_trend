import os
import requests
import feedparser
import google.generativeai as genai

REQUEST_TIMEOUT_SECONDS = 10
MAX_ENTRIES_PER_FEED = 3
TELEGRAM_MAX_MESSAGE_LENGTH = 3900

# 1. 환경 변수 설정
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# Gemini API 초기화 (가볍고 빠른 Flash 모델 사용)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')


def validate_required_env():
  """필수 환경 변수가 모두 설정되었는지 확인합니다."""
  required = {
    "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
    "CHAT_ID": CHAT_ID,
    "GEMINI_API_KEY": GEMINI_API_KEY,
  }
  missing = [key for key, value in required.items() if not value]
  if missing:
    raise ValueError(f"필수 환경 변수가 없습니다: {', '.join(missing)}")


def split_text(text, max_length=TELEGRAM_MAX_MESSAGE_LENGTH):
  """텔레그램 제한을 넘지 않도록 텍스트를 줄 단위로 분할합니다."""
  if len(text) <= max_length:
    return [text]

  chunks = []
  current_chunk = ""

  for line in text.splitlines(keepends=True):
    if len(current_chunk) + len(line) <= max_length:
      current_chunk += line
      continue

    if current_chunk:
      chunks.append(current_chunk)
      current_chunk = ""

    while len(line) > max_length:
      chunks.append(line[:max_length])
      line = line[max_length:]
    current_chunk = line

  if current_chunk:
    chunks.append(current_chunk)

  return chunks


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
        # User-Agent를 설정해야 Reddit 등에서 차단하지 않습니다.
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; AITrendBot/1.0)'}
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except requests.RequestException as exc:
            print(f"- RSS 수집 실패 ({source}): {exc}")
            continue
        
        # 소스별 상위 3개 기사만 추출
        for entry in feed.entries[:MAX_ENTRIES_PER_FEED]:
            title = getattr(entry, "title", "제목 없음")
            link = getattr(entry, "link", "링크 없음")
            collected_news.append(f"[{source}] {title}\nLink: {link}")
            
    return "\n\n".join(collected_news)

def generate_curation_report(news_data):
    """수집된 뉴스를 바탕으로 LLM에게 요약 및 인사이트 템플릿 작성을 요청합니다."""
    if not news_data.strip():
        return "오늘은 수집된 뉴스가 없어 리포트를 생성하지 못했습니다."
    
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

    🛠️ **[2. AI, IT 테크니컬 이슈]**
    - [기사 제목](기사 링크)
      └ 💬 코멘트: (엔지니어링/기술적 한계점이나 돌파구 1줄)
    - [기사 제목](기사 링크)
      └ 💬 코멘트: (내용...)

    💡 **[PM의 시선 (인사이트)]**
    - (오늘의 동향을 종합했을 때, 향후 AI 플랫폼 기획 및 인프라 도입 시 고려해야 할 점이나 너의 통찰력 있는 생각 1~2문단)
    """
    
    response = model.generate_content(prompt)
    return response.text

def send_telegram_message(text):
    """텔레그램으로 plain text 메시지를 전송합니다."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # 길이가 너무 길면 실패하므로 텔레그램 정책(4096자)보다 작게 분할 전송
    for chunk in split_text(text):
        payload = {
            "chat_id": CHAT_ID,
            "text": chunk,
        }
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()

if __name__ == "__main__":
    try:
        validate_required_env()

        print("1. RSS 뉴스 수집 시작...")
        raw_news = get_rss_news()

        print("2. LLM 요약 리포트 생성 중...")
        curated_message = generate_curation_report(raw_news)

        print("3. 텔레그램 전송 중...")
        send_telegram_message(curated_message)
        print("✅ 완료!")
    except Exception as exc:
        print(f"❌ 실패: {exc}")
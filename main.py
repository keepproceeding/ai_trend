import os
import requests
import feedparser

# GitHub Secrets에서 주입받을 환경변수
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # HTML 파싱 모드를 사용해 링크를 깔끔하게 전송
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    response = requests.post(url, json=payload)
    response.raise_for_status()

def fetch_and_send_news():
    # 예시: 구글 뉴스 RSS에서 최근 1일 내의 AI 관련 영문 뉴스 검색
    rss_url = "https://news.google.com/rss/search?q=Artificial+Intelligence+when:1d&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(rss_url)

    message = "<b>🌅 오늘의 AI & 테크 동향</b>\n\n"
    
    # 상위 5개의 기사만 추출
    for entry in feed.entries[:5]: 
        message += f"• <a href='{entry.link}'>{entry.title}</a>\n"

    send_telegram_message(message)

if __name__ == "__main__":
    fetch_and_send_news()
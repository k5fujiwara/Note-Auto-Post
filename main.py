import os
import feedparser
import random
import requests
from google import genai
from dotenv import load_dotenv

load_dotenv()

# --- 設定（GitHub Secretsから取得） ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN_NOTE")
THREADS_USER_ID = os.getenv("THREADS_USER_ID_NOTE")

def get_random_article():
    RSS_URL = "https://note.com/k5fujiwara/rss"
    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        return None
    return random.choice(feed.entries)

def generate_summary(article, has_reply):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # 確認した最新モデル ID を指定
    model_id = "gemini-2.5-flash"

    footer_inst = (
        "文末は、必ず『続きはリプライからどうぞ👇』という誘導にしてください。" 
        if has_reply else 
        "文末は、共感を呼ぶ結びや読者への問いかけで締め、リンク誘導はしないでください。"
    )

    prompt = f"""
    SNSで共感を生むプロライターとして、以下のnote記事をThreads用に要約して。
    【記事タイトル】: {article.title}
    【内容抜粋】: {article.description[:2500]} 

    【ルール】
    1. 1行目は強烈なフック。その後必ず空行。
    2. 箇条書きに頼らず、ストーリーを感じさせる短文で構成。
    3. 視覚的な「白さ（余白）」を大切にする。
    4. 最後に空行を入れ、{footer_inst}
    """
    
    try:
        response = client.models.generate_content(model=model_id, contents=prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Gemini API Error ({model_id}): {e}")
        return None

def post_to_threads(text, link=None):
    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    auth = {'access_token': THREADS_ACCESS_TOKEN}
    
    # 1. 親投稿
    res = requests.post(base_url, params={**auth, 'text': text, 'media_type': 'TEXT'}).json()
    parent_id = res.get('id')
    if not parent_id: return
    
    # 2. 公開
    requests.post(f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish", 
                  params={**auth, 'creation_id': parent_id})
    
    # 3. リプライ（リンクありの場合）
    if link:
        reply_res = requests.post(base_url, params={
            **auth, 'text': f"全文はこちら👇\n{link}", 
            'media_type': 'TEXT', 'reply_to_id': parent_id
        }).json()
        requests.post(f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish", 
                    params={**auth, 'creation_id': reply_res.get('id')})

if __name__ == "__main__":
    article = get_random_article()
    if article:
        is_link_mode = random.choice([True, False])
        summary = generate_summary(article, is_link_mode)
        
        if summary:
            target_link = article.link if is_link_mode else None
            post_to_threads(summary, target_link)
            print(f"Success: {article.title} (Link: {is_link_mode})")
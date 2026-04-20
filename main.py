import os
import sys
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
    print(f"Fetching RSS feed: {RSS_URL}")
    feed = feedparser.parse(RSS_URL)
    feed_status = getattr(feed, "status", "unknown")
    print(f"RSS fetch status: {feed_status}")

    if getattr(feed, "bozo", 0):
        print(f"RSS parse warning: {feed.bozo_exception}")

    if not feed.entries:
        print("Error: RSS fetch returned no entries.")
        return None

    article = random.choice(feed.entries)
    print(f"Selected article: {article.title}")
    return article

def generate_summary(article, has_reply):
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY is not set.")
        return None

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
        print(f"Generating summary with Gemini model: {model_id}")
        response = client.models.generate_content(model=model_id, contents=prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Gemini API Error ({model_id}): {e}")
        return None

def post_to_threads(text, link=None):
    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        print("Error: Threads credentials are not set.")
        return False

    base_url = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads"
    auth = {'access_token': THREADS_ACCESS_TOKEN}
    
    # 1. 親投稿の作成
    print("Creating Threads parent post container...")
    create_response = requests.post(
        base_url,
        params={**auth, 'text': text, 'media_type': 'TEXT'},
        timeout=30,
    )
    print(f"Threads create status: {create_response.status_code}")
    create_body = create_response.text
    print(f"Threads create response: {create_body}")

    try:
        res = create_response.json()
    except ValueError:
        print("Error: Parent container response was not valid JSON.")
        return False

    parent_id = res.get('id')
    if not parent_id: 
        print("Error: Parent container creation failed")
        return False
    
    # 2. 親投稿の公開 (Publish)
    # ⚠️ ここで取得できる ID が、リプライを紐づけるための「本当の投稿ID」になります
    print(f"Publishing Threads parent post: creation_id={parent_id}")
    publish_response = requests.post(
        f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish",
        params={**auth, 'creation_id': parent_id},
        timeout=30,
    )
    print(f"Threads publish status: {publish_response.status_code}")
    publish_body = publish_response.text
    print(f"Threads publish response: {publish_body}")

    try:
        publish_res = publish_response.json()
    except ValueError:
        print("Error: Parent publish response was not valid JSON.")
        return False

    post_id = publish_res.get('id')
    
    if not post_id:
        print("Error: Parent post publishing failed")
        return False
    
    # 3. リプライ（リンクありの場合）
    if link:
        # ⚠️ reply_to_id には「公開後の post_id」を指定する必要があります
        print(f"Creating reply container for post_id={post_id}")
        reply_response = requests.post(
            base_url,
            params={
                **auth,
                'text': f"全文はこちら👇\n{link}",
                'media_type': 'TEXT',
                'reply_to_id': post_id  # 修正：parent_id から post_id に変更
            },
            timeout=30,
        )
        print(f"Threads reply create status: {reply_response.status_code}")
        reply_body = reply_response.text
        print(f"Threads reply create response: {reply_body}")

        try:
            reply_container = reply_response.json()
        except ValueError:
            print("Error: Reply container response was not valid JSON.")
            return False
        
        reply_container_id = reply_container.get('id')
        if not reply_container_id:
            print("Error: Reply container creation failed")
            return False

        # リプライも公開処理が必要
        reply_publish_response = requests.post(
            f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish",
            params={**auth, 'creation_id': reply_container_id},
            timeout=30,
        )
        print(f"Threads reply publish status: {reply_publish_response.status_code}")
        reply_publish_body = reply_publish_response.text
        print(f"Threads reply publish response: {reply_publish_body}")

        try:
            reply_publish = reply_publish_response.json()
        except ValueError:
            print("Error: Reply publish response was not valid JSON.")
            return False

        if not reply_publish.get('id'):
            print("Error: Reply publish failed")
            return False

        print("Successfully posted with reply link.")

    return True

if __name__ == "__main__":
    article = get_random_article()
    if not article:
        sys.exit(1)

    is_link_mode = random.choice([True, False])
    print(f"Posting mode: {'reply link' if is_link_mode else 'text only'}")
    summary = generate_summary(article, is_link_mode)
    if not summary:
        print("Error: Summary generation failed.")
        sys.exit(1)

    target_link = article.link if is_link_mode else None
    if not post_to_threads(summary, target_link):
        sys.exit(1)

    print(f"Success: {article.title} (Link: {is_link_mode})")
import os
import sys
import time
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
DEFAULT_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

def get_gemini_models():
    raw_models = os.getenv("GEMINI_MODELS", "")
    models = [model.strip() for model in raw_models.split(",") if model.strip()]
    return models or DEFAULT_GEMINI_MODELS.copy()

def is_retryable_gemini_error(error):
    message = str(error).upper()
    retryable_markers = [
        "429",
        "500",
        "502",
        "503",
        "504",
        "RESOURCE_EXHAUSTED",
        "UNAVAILABLE",
        "DEADLINE_EXCEEDED",
        "INTERNAL",
    ]
    return any(marker in message for marker in retryable_markers)

def wait_for_threads_container(container_id, auth, label, max_checks=6, wait_seconds=10):
    status_url = f"https://graph.threads.net/v1.0/{container_id}"

    for attempt in range(1, max_checks + 1):
        print(f"Checking {label} container status ({attempt}/{max_checks}): {container_id}")
        status_response = requests.get(
            status_url,
            params={**auth, "fields": "status,error_message"},
            timeout=30,
        )
        print(f"{label} container status HTTP: {status_response.status_code}")
        print(f"{label} container status response: {status_response.text}")

        try:
            status_body = status_response.json()
        except ValueError:
            print(f"Error: {label} container status response was not valid JSON.")
            return False

        status = status_body.get("status")
        error_message = status_body.get("error_message")

        if status == "FINISHED":
            print(f"{label} container is ready to publish.")
            return True

        if status in {"ERROR", "EXPIRED"}:
            print(f"Error: {label} container status is {status}. detail={error_message}")
            return False

        if status == "PUBLISHED":
            print(f"{label} container is already published.")
            return True

        if attempt < max_checks:
            print(f"{label} container status is {status}. Waiting {wait_seconds} seconds before retry.")
            time.sleep(wait_seconds)

    print(f"Error: {label} container was not ready after {max_checks} checks.")
    return False

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
    model_ids = get_gemini_models()
    print(f"Configured Gemini models: {', '.join(model_ids)}")

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
    
    max_attempts = 4
    base_wait_seconds = 5
    last_error = None

    for model_index, model_id in enumerate(model_ids, start=1):
        print(f"Trying Gemini model {model_index}/{len(model_ids)}: {model_id}")

        for attempt in range(1, max_attempts + 1):
            try:
                print(f"Generating summary with Gemini model: {model_id} (attempt {attempt}/{max_attempts})")
                response = client.models.generate_content(model=model_id, contents=prompt)

                if not getattr(response, "text", None):
                    print(f"Gemini response was empty on model {model_id}.")
                    break

                print(f"Summary generated successfully with Gemini model: {model_id}")
                return response.text.strip()
            except Exception as e:
                last_error = e
                print(f"Gemini API Error ({model_id}) on attempt {attempt}: {e}")

                if not is_retryable_gemini_error(e):
                    print(f"Gemini error for {model_id} is not retryable. Switching models if available.")
                    break

                if attempt == max_attempts:
                    print(f"Gemini retry limit reached for {model_id}.")
                    break

                wait_seconds = base_wait_seconds * (2 ** (attempt - 1)) + random.randint(0, 2)
                print(f"Retrying Gemini after {wait_seconds} seconds.")
                time.sleep(wait_seconds)

        if model_index < len(model_ids):
            print(f"Falling back from {model_id} to the next Gemini model.")

    if last_error:
        print(f"Error: All Gemini models failed. Last error: {last_error}")
    else:
        print("Error: All Gemini models failed without returning text.")

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

    if not wait_for_threads_container(parent_id, auth, "Parent"):
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

        if not wait_for_threads_container(reply_container_id, auth, "Reply"):
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
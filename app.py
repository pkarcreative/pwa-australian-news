from flask import Flask, render_template, jsonify, send_from_directory, request, send_file, Response
import os
import io
import urllib.request
import json
from urllib.parse import quote
import pandas as pd
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
import praw
import time
import threading
import shutil
from pathlib import Path
from pcloud import PyCloud
import requests
import gc  # Garbage collector for explicit memory cleanup
import logging
import sys

# Configure logging to both file and console with UTF-8 encoding
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app_debug.log', encoding='utf-8'),
        logging.StreamHandler(sys.stderr)
    ]
)

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
reddit_client_id = os.getenv("REDDIT_CLIENT_ID")
reddit_client_secret = os.getenv("REDDIT_CLIENT_SECRET")
reddit_user_agent = os.getenv("REDDIT_USER_AGENT")
pcloud_username = os.getenv("PCLOUD_USERNAME")
pcloud_password = os.getenv("PCLOUD_PASSWORD")

# HTTP headers for requests
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

# Initialize OpenAI
client = OpenAI(api_key=openai_api_key)

# Initialize Reddit
reddit = praw.Reddit(
    client_id=reddit_client_id,
    client_secret=reddit_client_secret,
    user_agent=reddit_user_agent
)

app = Flask(__name__)

logger.info("="*60)
logger.info("Flask app initialized")
logger.info("="*60)

# TTS audio directory (local temp storage before upload)
TTS_AUDIO_DIR = os.path.join('static', 'tts_audio')
PCLOUD_FOLDER = '/tts_australian'  # pCloud folder for news TTS audio
PCLOUD_REDDIT_FOLDER = '/tts_australian_reddit'  # pCloud folder for Reddit TTS audio

# Global variable to cache news data (INFINITE CACHE)
NEWS_CACHE = {
    'data': None,
    'timestamp': None,
    'is_fetching': False,
    'lock': threading.Lock()
}

# Global variable to cache Reddit data
REDDIT_CACHE = {
    'data': None,
    'timestamp': None,
    'is_fetching': False,
    'lock': threading.Lock()
}

# Visitor tracking
VISITOR_STATS = {
    'countries': {},  # {country_code: count}
    'total': 0,
    'lock': threading.Lock()
}

def get_news_text_and_titles(url):
    """Scrape article text and title from URL with enhanced anti-bot headers"""

    # Enhanced headers to mimic a real browser from Google News referral
    enhanced_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-AU,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "identity",
        "Referer": "https://news.google.com/",  # Pretend we came from Google News
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0"
    }

    try:
        # Create request with cookie support
        import http.cookiejar
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

        req = urllib.request.Request(url, headers=enhanced_headers)
        response = opener.open(req, timeout=10)

        # Read with explicit encoding handling
        html_content = response.read()

        # Try to detect encoding from response headers
        encoding = response.headers.get_content_charset('utf-8')

        # Parse with BeautifulSoup using detected encoding
        soup = BeautifulSoup(html_content, "html.parser", from_encoding=encoding)

        # Extract article text
        paragraphs = soup.find_all('p')
        full_text = ' '.join([p.get_text(strip=True) for p in paragraphs])

        # Extract title
        article_title = None
        candidate = soup.select_one('h1')
        if candidate and candidate.get_text(strip=True):
            article_title = candidate.get_text(strip=True)

        # Check if article is too short
        if len(full_text.strip()) < 50:
            logger.info(f"FILTERED (too short, {len(full_text)} chars): {url}")
            return None, None

        return full_text, article_title

    except Exception as e:
        logger.warning(f"Scraping failed for {url[:50]}: {str(e)[:100]}")
        return None, None

def summarize_english(text, max_tokens=500):
    """SINGLE LLM call: AU relevance check → Generate summary → Validate summary for paywall using OpenAI gpt-5-nano"""
    max_retries = 3
    text_truncated = text[:8000]

    for attempt in range(max_retries):
        try:
            prompt = f"""Analyze this web content for an Australian news app. Follow these steps internally:

1. Check if relevant to Australia (politics, economy, business, cities, people, culture, sports, or international with AU angle)
   - If NOT relevant → Return exactly: NOT_RELEVANT

2. If relevant, create a 2-3 sentence summary (60 words max) focusing on key facts, names, events, details.

3. Check your summary: Does it contain actual news facts (names, events, places, numbers)?
   - If YES → Return ONLY the summary text (no labels, no step markers)
   - If NO or mentions "subscription required"/"unavailable" → Return exactly: PAYWALL_FOUND

IMPORTANT: Your response must be ONLY one of these:
- "NOT_RELEVANT" (if not about Australia)
- "PAYWALL_FOUND" (if no real content)
- The summary itself (just the text, no "STEP 2:" or other labels)

Text:
{text_truncated}

Response:"""

            response = client.chat.completions.create(
                model="gpt-5-nano-2025-08-07",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.3
            )
            
            result = response.choices[0].message.content.strip()

            # Filter based on LLM response
            if "NOT_RELEVANT" in result:
                logger.info("FILTERED (not Australia-relevant)")
                return None

            if "PAYWALL_FOUND" in result:
                logger.info("FILTERED (paywall detected in summary)")
                return None

            # Valid summary - return it
            return result

        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower():
                wait_time = (attempt + 1) * 5
                print(f"Rate limit hit, waiting {wait_time}s... (attempt {attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"Error in summarize_english: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    return None

    return None

def delete_all_pcloud_files(folder):
    """Delete public links AND files from pCloud"""
    try:
        print(f"\nDeleting all from pCloud folder: {folder}")
        pc = PyCloud(pcloud_username, pcloud_password)

        try:
            folder_contents = pc.listfolder(path=folder)

            if 'metadata' in folder_contents and 'contents' in folder_contents['metadata']:
                files = [item for item in folder_contents['metadata']['contents'] if not item['isfolder']]

                if not files:
                    print("No files to delete")
                    return True

                print(f"Found {len(files)} files...")

                # DELETE PUBLIC LINKS FIRST (critical!)
                for file_item in files:
                    file_path = file_item['path']
                    try:
                        # Delete public link if exists
                        requests.get("https://api.pcloud.com/deletepublink", params={
                            'path': file_path,
                            'username': pcloud_username,
                            'password': pcloud_password
                        })
                    except:
                        pass

                # Then delete files
                for file_item in files:
                    try:
                        pc.deletefile(path=file_item['path'])
                    except:
                        pass

                print(f"pCloud cleanup complete")
                return True
            else:
                print("Folder empty")
                return True

        except Exception as e:
            if "Directory does not exist" in str(e) or "2005" in str(e):
                print("Folder doesn't exist yet")
                return True
            else:
                raise e

    except Exception as e:
        print(f"Error: {e}")
        return False

def cleanup_local_tts_audio():
    """Delete local TTS audio files after upload"""
    try:
        if os.path.exists(TTS_AUDIO_DIR):
            print(f"Deleting local TTS audio from {TTS_AUDIO_DIR}...")
            shutil.rmtree(TTS_AUDIO_DIR)
            print("Local audio deleted")
    except Exception as e:
        print(f"Error deleting local audio: {e}")

def ensure_tts_directory():
    """Create TTS audio directory if it doesn't exist"""
    try:
        if not os.path.exists(TTS_AUDIO_DIR):
            os.makedirs(TTS_AUDIO_DIR)
            print(f"Created TTS directory: {TTS_AUDIO_DIR}")
    except Exception as e:
        print(f"Error creating TTS directory: {e}")

def upload_to_pcloud(local_filepath, pcloud_filename, folder):
    """Upload a file to pCloud storage"""
    try:
        pc = PyCloud(pcloud_username, pcloud_password)

        print(f"Uploading {pcloud_filename} to pCloud...", end=' ')

        # Upload file to pCloud folder
        upload_result = pc.uploadfile(files=[local_filepath], path=folder)

        if upload_result.get('result') == 0:
            print(f"Done")
            return True
        else:
            print(f"Upload failed: {upload_result}")
            return False

    except Exception as e:
        print(f"Error uploading to pCloud: {e}")
        return False

def generate_and_upload_tts(text, news_id, folder, prefix="news", max_retries=2):
    """Generate TTS ONE AT A TIME using OpenAI tts-1, upload to pCloud, delete immediately, free memory"""
    audio_filepath = None

    for attempt in range(max_retries):
        response = None  # Track response object for cleanup
        try:
            # Define file paths (MP3 format for OpenAI TTS)
            audio_filename = f"{prefix}_{news_id}.mp3"
            audio_filepath = os.path.join(TTS_AUDIO_DIR, audio_filename)

            if attempt == 0:
                print(f"[{news_id}] Generating TTS...", end=' ', flush=True)
            else:
                print(f"\n   [{news_id}] Retry {attempt}...", end=' ', flush=True)

            # Generate speech using OpenAI TTS API (tts-1 model - cheapest)
            response = client.audio.speech.create(
                model="tts-1",
                voice="alloy",
                input=text,
                timeout=60  # 60 second timeout
            )

            # Save to local file temporarily
            response.stream_to_file(audio_filepath)
            del response  # Free response object immediately
            response = None
            print(f"Saved", flush=True)

            # Upload to pCloud immediately
            print(f"   [{news_id}] Uploading...", end=' ', flush=True)
            upload_success = upload_to_pcloud(audio_filepath, audio_filename, folder)

            # IMMEDIATELY delete local file to free disk and memory
            if os.path.exists(audio_filepath):
                try:
                    file_size = os.path.getsize(audio_filepath) / 1024  # KB
                    os.remove(audio_filepath)
                    print(f"Deleted ({file_size:.1f}KB)", flush=True)
                except Exception as e:
                    print(f"Delete failed: {e}")

            # Force garbage collection to free memory NOW
            gc.collect()

            if upload_success:
                print(f"   [{news_id}] Complete\n", flush=True)
                return True
            else:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                else:
                    return False

        except Exception as e:
            print(f"Error: {str(e)[:100]}")

            # Clean up response object
            if response is not None:
                del response
                response = None

            # Clean up local file on error
            if audio_filepath and os.path.exists(audio_filepath):
                try:
                    os.remove(audio_filepath)
                except:
                    pass

            # Force garbage collection
            gc.collect()

            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            else:
                return False

    return False

def generate_all_tts(df_news, folder, prefix="news"):
    """Generate TTS SEQUENTIALLY - ONE at a time, upload, get URL, cache in DataFrame"""
    print(f"\nSEQUENTIAL TTS GENERATION FOR {len(df_news)} ITEMS")
    print("="*60)
    print("STRICT SEQUENTIAL MODE: Generate -> Upload -> Get URL -> Cache -> Wait -> Next")
    print("="*60 + "\n")

    # Ensure local temp directory exists
    ensure_tts_directory()

    success_count = 0
    failed_ids = []
    total_articles = len(df_news)

    # Add tts_code column to DataFrame to store permanent pCloud link codes
    df_news['tts_code'] = None

    for idx, row in df_news.iterrows():
        news_id = idx + 1  # 1-indexed
        summary = row.get('summary', '')

        print(f"Article {news_id}/{total_articles}")

        if not summary or pd.isna(summary):
            print(f"Skipping (no summary)\n")
            continue

        if generate_and_upload_tts(summary, news_id, folder, prefix):
            success_count += 1

            # Wait for pCloud to index the uploaded file
            print(f"   [{news_id}] Waiting for pCloud indexing...", end=' ', flush=True)
            time.sleep(2)  # pCloud needs time to propagate the file
            print(f"Done", flush=True)

            # Get and cache pCloud public link code after indexing delay
            audio_filename = f"{prefix}_{news_id}.mp3"
            print(f"   [{news_id}] Getting pCloud public link code...", end=' ', flush=True)
            link_code = get_pcloud_public_code(audio_filename, folder)

            # Store the link code in DataFrame (permanent, won't expire!)
            if link_code:
                df_news.at[idx, 'tts_code'] = link_code
                print(f"Code: {link_code[:10]}...", flush=True)
            else:
                print(f"Failed to get code", flush=True)
        else:
            failed_ids.append(news_id)
            print(f"   [{news_id}] Failed\n")

        # Wait before next article (memory cleanup time)
        if idx < len(df_news) - 1:
            print(f"Waiting 4 seconds for memory cleanup...\n")
            time.sleep(4)

    print("="*60)
    print(f"COMPLETE: {success_count}/{total_articles} TTS files generated")
    if failed_ids:
        print(f"Failed IDs: {failed_ids}")
    print("="*60 + "\n")

    # Final cleanup of temp directory
    cleanup_local_tts_audio()

    # Final garbage collection
    gc.collect()

    return success_count

def fetch_australian_news():
    """Fetch and process Australian news from GDELT using urllib"""
    print("\n" + "="*60)
    print("FETCHING AUSTRALIAN NEWS FROM GDELT")
    print("="*60)
    
    URLbase = "https://api.gdeltproject.org/api/v2/doc/doc"
    format_type = "json"
    mode_type = "ArtList"
    sort_type = "DateDesc"
    language = "eng"  # English
    maxrecords = 20
    
    # Use timezone-aware datetime
    now = datetime.now(timezone.utc)
    past_10h = now - timedelta(hours=10)
    startdatetime = past_10h.strftime("%Y%m%d%H%M%S")
    enddatetime = now.strftime("%Y%m%d%H%M%S")
    
    list_countries = ['AS']  # Australia (AS in FIPS/GDELT, not AU which is Austria!)
    all_articles = []
    
    for country in list_countries:
        # Query for articles FROM Australia
        full_query = (
            f"{URLbase}?format={format_type}"
            f"&query=%20sourcecountry:{country}%20sourcelang:{language}"
            f"&mode={mode_type}"
            f"&maxrecords={maxrecords}"
            f"&sort={sort_type}"
            f"&startdatetime={startdatetime}"
            f"&enddatetime={enddatetime}"
        )
        
        try:
            for attempt in range(4):
                print(f"\nCalling GDELT API for {country}... (attempt {attempt+1}/4)")
                print(f"URL: {full_query[:100]}...")
                
                # USE urllib.request.urlopen() - This avoids 429 rate limit!
                req = urllib.request.Request(full_query, headers=headers)
                response = urllib.request.urlopen(req, timeout=30)
                
                response_data = response.read().decode('utf-8')
                
                print(f"Response received ({len(response_data)} characters)")
                
                # Parse JSON
                data_json = json.loads(response_data)
                
                if 'articles' not in data_json:
                    print("No 'articles' key in response")
                    if attempt < 3:
                        time.sleep(3)
                        continue
                    else:
                        continue
                
                # Success - break retry loop
                break
            
            articles = data_json['articles']
            print(f"Found {len(articles)} articles")
            
            df_AU = pd.DataFrame(articles)
            
            # Filter Australian domains (.com.au, .net.au, .org.au, .gov.au, .edu.au)
            if 'url' in df_AU.columns:
                initial_count = len(df_AU)
                # Match any .au domain
                df_AU = df_AU[df_AU['url'].str.contains('.au', case=False, na=False)]
                print(f"Filtered to Australian (.au) domains: {len(df_AU)} (removed {initial_count - len(df_AU)})")
            
            if df_AU.empty:
                print("No articles after domain filtering")
                continue

            print(f"Scraping article content from {len(df_AU)} articles...")

            # Scrape with progress indicator
            scraped_results = []
            for idx, url in enumerate(df_AU['url'], 1):
                print(f"  [{idx}/{len(df_AU)}] {url[:60]}...", end=' ', flush=True)
                result = get_news_text_and_titles(url)
                scraped_results.append(result)
                if result[0] is not None:
                    print(f"✓ ({len(result[0])} chars)")
                else:
                    print("✗ Failed")

            df_AU['News_Text'] = [item[0] for item in scraped_results]
            scraped_titles = [item[1] for item in scraped_results]

            # Use scraped title as the main title (overwrite GDELT's empty titles)
            for idx, scraped_title in enumerate(scraped_titles):
                if scraped_title:  # If scraping found a title
                    df_AU.at[df_AU.index[idx], 'title'] = scraped_title

            # Remove failed scrapes
            pre_filter_count = len(df_AU)
            df_AU = df_AU.dropna(subset=['News_Text'])
            print(f"\n✓ Successfully scraped: {len(df_AU)}/{pre_filter_count} articles")
            print(f"Note: Australian relevance will be checked by LLM during summarization")

            all_articles.extend(df_AU.to_dict('records'))
            
        except urllib.error.HTTPError as e:
            print(f"HTTP Error {e.code} for {country}")
            print(f"Response: {e.read().decode('utf-8')[:200]}")
            continue
        except Exception as e:
            print(f"Error fetching data for {country}: {type(e).__name__}: {e}")
            continue
    
    if not all_articles:
        print("\nNo data collected from GDELT!")
        return pd.DataFrame()
    
    df_all_AU = pd.DataFrame(all_articles)
    
    # Clean data
    print(f"\nCleaning data...")
    initial_count = len(df_all_AU)
    
    df_all_AU = df_all_AU.dropna(subset=['News_Text'])
    print(f"After removing empty articles: {len(df_all_AU)} (removed {initial_count - len(df_all_AU)})")
    
    if df_all_AU.empty:
        print("No valid articles after cleaning!")
        return pd.DataFrame()
    
    # Remove duplicates
    if 'title' in df_all_AU.columns:
        df_all_AU = df_all_AU.drop_duplicates(subset=['title']).reset_index(drop=True)
        print(f"After removing duplicates: {len(df_all_AU)}")

    # **LIMIT TO 3 NEWS FOR MEMORY CONSTRAINTS**
    """
    if len(df_all_AU) > 3:
        print(f"\nLIMITING to 10 news  articles for memory constraints (was {len(df_all_AU)})")
        df_all_AU = df_all_AU.head(10)
    """

    # Generate summaries
    print(f"\nGenerating English summaries for {len(df_all_AU)} articles...")
    summaries = []
    for idx, text in enumerate(df_all_AU["News_Text"]):
        print(f"Summarizing article {idx+1}/{len(df_all_AU)}...", end=' ')
      # print(f"news text:{text}")
        summary = summarize_english(text)
        summaries.append(summary)
        print("Done" if summary else "Failed")
        time.sleep(1)

    df_all_AU["summary"] = summaries
    df_all_AU = df_all_AU.dropna(subset=['summary'])
    df_all_AU = df_all_AU.reset_index(drop=True)  # Reset indices to 0,1,2... for consistent news_id

    print(f"{len(df_all_AU)} articles with summaries")

    if df_all_AU.empty:
        print("No articles with valid summaries!")
        return pd.DataFrame()

    # Keep only required columns
    cols_to_keep = ["url", "title", "socialimage", "language", "summary"]

    # Add missing columns with empty values FIRST
    for col in cols_to_keep:
        if col not in df_all_AU.columns:
            df_all_AU[col] = ""

    # NOW fix missing titles: use first 50 chars of summary
    for idx, row in df_all_AU.iterrows():
        if not row.get('title') or row.get('title').strip() == '':
            df_all_AU.at[idx, 'title'] = row['summary'][:50] + "..."

    df_all_AU = df_all_AU[cols_to_keep]

    print(f"\nSUCCESS: {len(df_all_AU)} Australian news articles ready!")
    print("="*60 + "\n")

    # Generate TTS audio for all summaries
    generate_all_tts(df_all_AU, PCLOUD_FOLDER, prefix="news")

    return df_all_AU

def fetch_reddit_discussions():
    """Fetch Australian Reddit discussions with top comments"""
    print("\n" + "="*60)
    print("FETCHING AUSTRALIAN REDDIT DISCUSSIONS")
    print("="*60)

    # Australian subreddits to fetch from
    subreddits = ['australia', 'AustralianPolitics', 'sydney', 'melbourne']
    all_discussions = []

    # Time limit: last 24 hours
    time_24h_ago = time.time() - (24 * 60 * 60)

    for subreddit_name in subreddits:
        try:
            print(f"\nFetching from r/{subreddit_name}...")
            subreddit = reddit.subreddit(subreddit_name)

            # Get hot posts from last 24 hours
            for post in subreddit.hot(limit=10):
                # Check if post is within last 24 hours
                if post.created_utc < time_24h_ago:
                    continue

                # Skip stickied posts
                if post.stickied:
                    continue

                # Get top 5 comments
                post.comment_sort = 'top'
                post.comment_limit = 5
                top_comments = []

                try:
                    post.comments.replace_more(limit=0)  # Don't fetch "load more" comments
                    for comment in post.comments[:5]:
                        if hasattr(comment, 'body') and comment.score > 2:  # Min 2 upvotes
                            top_comments.append({
                                'body': comment.body[:500],  # Limit comment length
                                'score': comment.score
                            })
                except:
                    pass

                # Get best quality image available
                image_url = None
                try:
                    if hasattr(post, 'preview') and 'images' in post.preview:
                        # Use preview image (higher quality than thumbnail)
                        image_url = post.preview['images'][0]['source']['url'].replace('&amp;', '&')
                    elif post.thumbnail and post.thumbnail.startswith('http'):
                        # Fallback to thumbnail if preview not available
                        image_url = post.thumbnail
                except:
                    pass

                # Prepare discussion data
                discussion = {
                    'title': post.title,
                    'selftext': post.selftext[:1000] if post.selftext else '',  # Post content
                    'url': f"https://reddit.com{post.permalink}",
                    'subreddit': subreddit_name,
                    'score': post.score,
                    'num_comments': post.num_comments,
                    'created_utc': post.created_utc,
                    'top_comments': top_comments,
                    'thumbnail': image_url
                }

                all_discussions.append(discussion)
                print(f"  {post.title[:50]}... ({post.score} upvotes, {post.num_comments} comments)")

            time.sleep(1)  # Rate limiting

        except Exception as e:
            print(f"Error fetching from r/{subreddit_name}: {e}")
            continue

    if not all_discussions:
        print("\nNo discussions collected!")
        return pd.DataFrame()

    print(f"\nCollected {len(all_discussions)} discussions")

    # Convert to DataFrame
    df_reddit = pd.DataFrame(all_discussions)

    # Sort by score (engagement)
    df_reddit = df_reddit.sort_values('score', ascending=False).reset_index(drop=True)

    # **LIMIT TO 15 DISCUSSIONS FOR MEMORY CONSTRAINTS**
    if len(df_reddit) > 15:
        print(f"\nLIMITING to 3 discussions for memory constraints (was {len(df_reddit)})")
        df_reddit = df_reddit.head(15)

    # Generate summaries combining post + top comments
    print(f"\nGenerating summaries for {len(df_reddit)} discussions...")
    summaries = []

    for idx, row in df_reddit.iterrows():
        print(f"Summarizing discussion {idx+1}/{len(df_reddit)}...", end=' ')

        # Combine post and comments for summary
        combined_text = f"Title: {row['title']}\n\nPost: {row['selftext']}\n\n"
        if row['top_comments']:
            combined_text += "Top Comments:\n"
            for i, comment in enumerate(row['top_comments'][:3], 1):
                combined_text += f"{i}. {comment['body']}\n"

        # Summarize with retry logic using OpenAI gpt-5-nano
        prompt = f"""Summarize this Reddit discussion including the main post and key points from top comments. Keep it concise (60 words max):

{combined_text}"""

        summary = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model="gpt-5-nano",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200,
                    temperature=0.3
                )
                summary = response.choices[0].message.content.strip()
                summaries.append(summary)
                print("Done")
                break
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower():
                    wait_time = (attempt + 1) * 5
                    print(f"Rate limit, waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    if attempt < max_retries - 1:
                        time.sleep(2)
                    else:
                        print(f"Failed ({str(e)[:50]}...)")
                        summaries.append(row['title'])  # Fallback to title

        if summary is None and len(summaries) <= idx:
            summaries.append(row['title'])  # Fallback if all retries failed

        time.sleep(1)

    df_reddit['summary'] = summaries

    # Add TTS (using same function)
    print(f"\nGenerating TTS for discussions...")
    generate_all_tts(df_reddit, PCLOUD_REDDIT_FOLDER, prefix="reddit")

    print(f"\nSUCCESS: {len(df_reddit)} Reddit discussions ready!")
    print("="*60 + "\n")

    return df_reddit

def get_pcloud_public_code(filename, folder):
    """Get PERMANENT public link code for a file from pCloud"""
    try:
        file_path = f'{folder}/{filename}'

        # First, try to create public link
        response = requests.get("https://api.pcloud.com/getfilepublink", params={
            'path': file_path,
            'username': pcloud_username,
            'password': pcloud_password
        })

        if response.status_code == 200:
            data = response.json()
            if data.get('result') == 0:
                return data.get('code')
            else:
                # Link already exists - DELETE IT and create new one
                if 'already' in str(data.get('error', '')).lower():
                    print(f"   Old link exists, deleting...")
                    # Delete old link
                    requests.get("https://api.pcloud.com/deletepublink", params={
                        'path': file_path,
                        'username': pcloud_username,
                        'password': pcloud_password
                    })
                    # Create fresh link
                    response2 = requests.get("https://api.pcloud.com/getfilepublink", params={
                        'path': file_path,
                        'username': pcloud_username,
                        'password': pcloud_password
                    })
                    if response2.status_code == 200:
                        data2 = response2.json()
                        if data2.get('result') == 0:
                            return data2.get('code')
                return None
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def process_news_for_api(df_news):
    """Convert DataFrame to API-friendly format with server-proxied TTS URLs"""
    if df_news is None or df_news.empty:
        return []

    news_list = []

    for idx, row in df_news.iterrows():
        news_id = idx + 1

        # Degrade image quality using URL parameters
        image_url = row.get('socialimage', '')
        if pd.notna(image_url) and str(image_url).startswith('http'):
            if '?' in image_url:
                image_url += '&width=400&quality=60'
            else:
                image_url += '?width=400&quality=60'
        else:
            image_url = 'https://via.placeholder.com/400x250/4A90E2/ffffff?text=No+Image'

        # Check if we have a pCloud link code
        tts_code = row.get('tts_code', None)

        # Construct our server endpoint URL (not direct pCloud URL)
        timestamp = int(NEWS_CACHE['timestamp'].timestamp()) if NEWS_CACHE['timestamp'] else 0
        tts_url = f"/api/tts/{news_id}?v={timestamp}" if tts_code and not pd.isna(tts_code) else None

        news_item = {
            'id': news_id,
            'title': row.get('title', 'Title not available'),
            'summary': row.get('summary', 'Summary not available'),
            'source': '',  # Hidden in UI
            'source_url': row.get('url', '#'),
            'image': image_url,
            'category': '',  # Hidden in UI
            'tts_url': tts_url  # Our server endpoint that proxies pCloud
        }
        news_list.append(news_item)

    return news_list

@app.route('/')
def landing():
    """Landing page with news/reddit options"""
    country = request.headers.get('CF-IPCountry', 'Unknown')
    with VISITOR_STATS['lock']:
        VISITOR_STATS['total'] += 1
        VISITOR_STATS['countries'][country] = VISITOR_STATS['countries'].get(country, 0) + 1
    return render_template('landing.html')

@app.route('/news')
def news_page():
    """News page"""
    return render_template('viewer.html', content_type='news')

@app.route('/reddit')
def reddit_page():
    """Reddit page"""
    return render_template('viewer.html', content_type='reddit')

@app.route('/api/news')
def get_news():
    """Get cached news - does NOT fetch automatically"""

    print(f"\n/api/news called")

    # Check if cache exists
    if NEWS_CACHE['data'] is not None:
        print("Using cached news")
        news_list = process_news_for_api(NEWS_CACHE['data'])
        return jsonify(news_list)
    else:
        print("No cached news available")
        return jsonify({
            'error': 'No news available',
            'message': 'No news cached. Please call /api/fetch-news to fetch fresh news.'
        }), 404

@app.route('/api/fetch-news', methods=['GET', 'POST'])
def fetch_news_endpoint():
    """Fetch fresh news, generate summaries and TTS, upload to pCloud

    This is the ONLY endpoint that fetches new news.
    Call this via cron job to update news periodically.
    """

    print(f"\n/api/fetch-news called")

    # Check if already fetching
    with NEWS_CACHE['lock']:
        if NEWS_CACHE['is_fetching']:
            print("Already fetching news...")
            return jsonify({
                'status': 'fetching',
                'message': 'News fetch already in progress. Please wait.'
            }), 409  # 409 Conflict

        NEWS_CACHE['is_fetching'] = True

    try:
        # Delete all old TTS files from pCloud news folder
        print("Cleaning old pCloud files...")
        delete_success = delete_all_pcloud_files(PCLOUD_FOLDER)
        if not delete_success:
            print("Warning: Failed to delete some pCloud files, continuing anyway...")

        # Fetch fresh news (includes TTS generation and upload)
        print("Fetching news...")
        df_news = fetch_australian_news()

        if df_news.empty:
            with NEWS_CACHE['lock']:
                NEWS_CACHE['is_fetching'] = False
            return jsonify({
                'status': 'error',
                'message': 'No news could be fetched',
                'count': 0
            }), 500

        # Update cache (even if some TTS failed, we still have news data)
        with NEWS_CACHE['lock']:
            NEWS_CACHE['data'] = df_news
            NEWS_CACHE['timestamp'] = datetime.now(timezone.utc)
            NEWS_CACHE['is_fetching'] = False

        news_list = process_news_for_api(df_news)

        # Count how many TTS URLs are valid
        tts_success_count = sum(1 for item in news_list if item.get('tts_url'))

        print(f"Process complete: {len(news_list)} articles, {tts_success_count} TTS files")

        return jsonify({
            'status': 'success',
            'message': 'News fetched and processed successfully',
            'count': len(news_list),
            'tts_count': tts_success_count,
            'timestamp': NEWS_CACHE['timestamp'].isoformat(),
            'note': 'Some TTS may have failed due to memory constraints' if tts_success_count < len(news_list) else None
        })

    except Exception as e:
        print(f"Error in /api/fetch-news: {str(e)}")
        import traceback
        traceback.print_exc()
        with NEWS_CACHE['lock']:
            NEWS_CACHE['is_fetching'] = False
        return jsonify({
            'status': 'error',
            'message': str(e),
            'type': type(e).__name__
        }), 500

@app.route('/api/fetch-reddit', methods=['GET', 'POST'])
def fetch_reddit_endpoint():
    """Fetch Reddit discussions"""

    print(f"\n/api/fetch-reddit called")

    with REDDIT_CACHE['lock']:
        if REDDIT_CACHE['is_fetching']:
            return jsonify({
                'status': 'fetching',
                'message': 'Reddit fetch already in progress.'
            }), 409

        REDDIT_CACHE['is_fetching'] = True

    try:
        # Delete all old TTS files from pCloud reddit folder
        print("Cleaning old Reddit pCloud files...")
        delete_success = delete_all_pcloud_files(PCLOUD_REDDIT_FOLDER)
        if not delete_success:
            print("Warning: Failed to delete some pCloud files, continuing anyway...")

        df_reddit = fetch_reddit_discussions()

        if df_reddit.empty:
            with REDDIT_CACHE['lock']:
                REDDIT_CACHE['is_fetching'] = False
            return jsonify({
                'status': 'error',
                'message': 'No Reddit discussions fetched',
                'count': 0
            }), 500

        with REDDIT_CACHE['lock']:
            REDDIT_CACHE['data'] = df_reddit
            REDDIT_CACHE['timestamp'] = datetime.now(timezone.utc)
            REDDIT_CACHE['is_fetching'] = False

        return jsonify({
            'status': 'success',
            'message': 'Reddit discussions fetched successfully',
            'count': len(df_reddit),
            'timestamp': REDDIT_CACHE['timestamp'].isoformat()
        })

    except Exception as e:
        print(f"Error in /api/fetch-reddit: {str(e)}")
        with REDDIT_CACHE['lock']:
            REDDIT_CACHE['is_fetching'] = False
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/reddit')
def get_reddit():
    """Get cached Reddit discussions"""
    if REDDIT_CACHE['data'] is not None:
        reddit_list = []
        for idx, row in REDDIT_CACHE['data'].iterrows():
            reddit_id = idx + 1
            tts_code = row.get('tts_code', None)
            timestamp = int(REDDIT_CACHE['timestamp'].timestamp()) if REDDIT_CACHE['timestamp'] else 0
            tts_url = f"/api/tts-reddit/{reddit_id}?v={timestamp}" if tts_code and not pd.isna(tts_code) else None

            reddit_item = {
                'id': reddit_id,
                'title': row.get('title', 'No title'),
                'summary': row.get('summary', ''),
                'source': f"r/{row.get('subreddit', 'australia')}",
                'source_url': row.get('url', '#'),
                'image': row.get('thumbnail') or 'https://via.placeholder.com/400x250/FF4500/ffffff?text=Reddit',
                'category': f"{row.get('score', 0)} upvotes {row.get('num_comments', 0)} comments",
                'tts_url': tts_url
            }
            reddit_list.append(reddit_item)

        return jsonify(reddit_list)
    else:
        return jsonify({
            'error': 'No Reddit data available',
            'message': 'Call /api/fetch-reddit first'
        }), 404

@app.route('/api/status')
def get_status():
    """Get cache status"""
    news_cached = NEWS_CACHE['data'] is not None
    reddit_cached = REDDIT_CACHE['data'] is not None

    status = {
        'news': {
            'cached': news_cached,
            'count': len(NEWS_CACHE['data']) if news_cached else 0,
            'is_fetching': NEWS_CACHE['is_fetching'],
            'last_updated': NEWS_CACHE['timestamp'].isoformat() if NEWS_CACHE['timestamp'] else None
        },
        'reddit': {
            'cached': reddit_cached,
            'count': len(REDDIT_CACHE['data']) if reddit_cached else 0,
            'is_fetching': REDDIT_CACHE['is_fetching'],
            'last_updated': REDDIT_CACHE['timestamp'].isoformat() if REDDIT_CACHE['timestamp'] else None
        }
    }

    return jsonify(status)

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def service_worker():
    response = send_from_directory('static', 'sw.js')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/offline')
def offline():
    return render_template('index.html')

@app.route('/api/stats')
def get_stats():
    """Get visitor statistics"""
    with VISITOR_STATS['lock']:
        return jsonify({
            'total_visitors': VISITOR_STATS['total'],
            'countries': dict(sorted(VISITOR_STATS['countries'].items(), key=lambda x: x[1], reverse=True))
        })

@app.route('/api/tts/<int:news_id>')
def stream_tts(news_id):
    """Stream TTS audio from pCloud using permanent public link code"""

    print(f"\n/api/tts/{news_id} called")

    # Check if news data exists
    if NEWS_CACHE['data'] is None or NEWS_CACHE['data'].empty:
        return jsonify({
            'error': 'No news data available',
            'message': 'Please fetch news first via /api/fetch-news'
        }), 404

    # Validate news_id
    if news_id < 1 or news_id > len(NEWS_CACHE['data']):
        return jsonify({
            'error': 'Invalid news ID',
            'message': f'News ID must be between 1 and {len(NEWS_CACHE["data"])}'
        }), 400

    try:
        # Get the pCloud link code from DataFrame
        idx = news_id - 1
        tts_code = NEWS_CACHE['data'].iloc[idx].get('tts_code')

        if not tts_code or pd.isna(tts_code):
            return jsonify({
                'error': 'No TTS available',
                'message': f'TTS for news {news_id} not available'
            }), 404

        # Get download URL from pCloud using the permanent link code
        api_url = "https://api.pcloud.com/getpublinkdownload"
        params = {
            'code': tts_code,
            'forcedownload': 0  # Stream, don't force download
        }

        response = requests.get(api_url, params=params)
        if response.status_code == 200:
            data = response.json()
            if data.get('result') == 0:
                # Get download URL from response
                download_url = f"https://{data['hosts'][0]}{data['path']}"

                # Stream from pCloud to client
                print(f"Streaming from pCloud: news_{news_id}.mp3")
                pcloud_response = requests.get(download_url, stream=True)

                # Return streaming response
                def generate():
                    for chunk in pcloud_response.iter_content(chunk_size=8192):
                        yield chunk

                return Response(
                    generate(),
                    mimetype='audio/mpeg',
                    headers={
                        'Content-Type': 'audio/mpeg',
                        'Accept-Ranges': 'bytes',
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache',
                        'Expires': '0'
                    }
                )
            else:
                print(f"pCloud API error: {data.get('error')}")
                return jsonify({
                    'error': 'pCloud error',
                    'message': data.get('error')
                }), 500
        else:
            return jsonify({
                'error': 'Failed to get download link',
                'message': 'pCloud API error'
            }), 500

    except Exception as e:
        print(f"Error in /api/tts/{news_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': 'Internal server error',
            'message': str(e)
        }), 500

@app.route('/api/tts-reddit/<int:reddit_id>')
def stream_tts_reddit(reddit_id):
    """Stream Reddit TTS audio from pCloud"""
    print(f"\n/api/tts-reddit/{reddit_id} called")

    if REDDIT_CACHE['data'] is None or REDDIT_CACHE['data'].empty:
        return jsonify({
            'error': 'No Reddit data available',
            'message': 'Please fetch Reddit first via /api/fetch-reddit'
        }), 404

    if reddit_id < 1 or reddit_id > len(REDDIT_CACHE['data']):
        return jsonify({
            'error': 'Invalid Reddit ID',
            'message': f'Reddit ID must be between 1 and {len(REDDIT_CACHE["data"])}'
        }), 400

    try:
        idx = reddit_id - 1
        tts_code = REDDIT_CACHE['data'].iloc[idx].get('tts_code')

        if not tts_code or pd.isna(tts_code):
            return jsonify({
                'error': 'No TTS available',
                'message': f'TTS for Reddit discussion {reddit_id} not available'
            }), 404

        api_url = "https://api.pcloud.com/getpublinkdownload"
        params = {
            'code': tts_code,
            'forcedownload': 0
        }

        response = requests.get(api_url, params=params)
        if response.status_code == 200:
            data = response.json()
            if data.get('result') == 0:
                download_url = f"https://{data['hosts'][0]}{data['path']}"
                print(f"Streaming from pCloud: reddit_{reddit_id}.mp3")
                pcloud_response = requests.get(download_url, stream=True)

                def generate():
                    for chunk in pcloud_response.iter_content(chunk_size=8192):
                        yield chunk

                return Response(
                    generate(),
                    mimetype='audio/mpeg',
                    headers={
                        'Content-Type': 'audio/mpeg',
                        'Accept-Ranges': 'bytes',
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache',
                        'Expires': '0'
                    }
                )

    except Exception as e:
        print(f"Error in /api/tts-reddit/{reddit_id}: {str(e)}")
        return jsonify({
            'error': 'Internal server error',
            'message': str(e)
        }), 500


if __name__ == '__main__':
    print("\n" + "="*70)
    print("AUSTRALIAN NEWS & REDDIT PWA - STARTING")
    print("="*70)
    print("\nFeatures:")
    print("  - urllib.request (avoids GDELT 429 rate limit)")
    print("  - OpenAI API (gpt-5-nano for summarization + tts-1 for TTS)")
    print("  - Australian news filtering:")
    print("    * sourcecountry:AS (articles FROM Australia)")
    print("    * .au domain filtering")
    print("    * Referer spoofing (pretend from Google News)")
    print("    * HTTP cookie jar support")
    print("    * Paywall/subscription wall detection")
    print("    * Australia-relevance keyword filtering (50+ keywords)")
    print("  - Reddit integration (r/australia, r/AustralianPolitics, etc.)")
    print("  - pCloud storage for TTS audio")
    print("\n  Best sources: ABC, Guardian, SBS, government sites")
    print("\nEndpoints:")
    print("   - http://localhost:5000/                     (Landing page)")
    print("   - http://localhost:5000/news                 (News page)")
    print("   - http://localhost:5000/reddit               (Reddit page)")
    print("   - http://localhost:5000/api/fetch-news       (Fetch news)")
    print("   - http://localhost:5000/api/fetch-reddit     (Fetch Reddit)")
    print("   - http://localhost:5000/api/status           (Cache status)")
    print("\nLimits: 3 news + 3 Reddit items (memory constraints)")
    print("Storage: pCloud folder /tts_australian")
    print("Updates: Use external cron to fetch fresh content periodically")
    print("\nTTS: OpenAI tts-1 model (cheapest) with alloy voice")
    print("Audio format: MP3 (audio/mpeg)")
    print("\n" + "="*70 + "\n")

    # Disable reloader to prevent duplicate calls
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
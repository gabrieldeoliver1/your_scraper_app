import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime
import time
from newspaper import Article, ArticleException
import re

# For accessing Flask app context in the thread
from flask import current_app

# Import DB functions within the thread
from database import get_db, add_article, get_scraper_status, set_scraper_status, update_scraper_progress_for_site

MAX_PAGES_PER_SITE = 50 # Limit the number of pages to crawl per site to prevent endless crawling
CRAWL_DELAY = 1 # Seconds to wait between requests to the same domain

# Dictionary to store crawled URLs per site to avoid re-scraping in the SAME RUN.
# This is in-memory. For persistence across app restarts, you would store this in DB.
_crawled_urls_per_site_session = {}

def get_html(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def extract_article_details_with_newspaper(article_url):
    try:
        # Pass article_url and a language for better parsing
        article = Article(article_url, language='pt')
        article.download() # Downloads the article's HTML
        article.parse()    # Parses the HTML to extract content

        title = article.title if article.title else 'Título Não Encontrado'
        content = article.text if article.text else 'Conteúdo Não Encontrado'
        # Convert datetime object to ISO format string for consistent storage in DB
        published_date = article.publish_date.isoformat() if article.publish_date else None

        return {'title': title, 'content': content, 'published_date': published_date, 'url': article_url}
    except ArticleException as e:
        # print(f"Error extracting with newspaper3k from {article_url}: {e}") # Keep this for debugging if needed
        return None # Return None if newspaper3k fails to extract a valid article
    except Exception as e:
        print(f"General error with newspaper3k on {article_url}: {e}")
        return None

def scrape_website_threaded(app_context, site_id, base_url, search_terms):
    with app_context: # Activate Flask app context for DB operations within this thread
        print(f"\n--- Thread started for site: {base_url} (ID: {site_id}) ---")
        print(f"Search terms for this run: {search_terms}")
        
        if site_id not in _crawled_urls_per_site_session:
            _crawled_urls_per_site_session[site_id] = set()

        crawled_urls_for_site = _crawled_urls_per_site_session[site_id]
        to_crawl_urls = [base_url] # Start crawling from the base URL
        parsed_base_netloc = urlparse(base_url).netloc # Get the domain for internal links filtering

        pages_crawled_count = 0

        # Initial progress update for this specific site
        # Status 'running' is default, and max_pages_to_crawl is MAX_PAGES_PER_SITE for this site
        update_scraper_progress_for_site(site_id, 0, MAX_PAGES_PER_SITE, status='running')

        try: # Added try-finally to ensure progress is updated on exit
            while to_crawl_urls and pages_crawled_count < MAX_PAGES_PER_SITE:
                # Check for global stop signal from the database
                if get_scraper_status()['status'] == 'stopped': # Get 'status' key from the dict
                    print(f"Scraper for {base_url} received global stop signal. Stopping.")
                    break

                current_url = to_crawl_urls.pop(0)

                if current_url in crawled_urls_for_site:
                    print(f"  Skipping already crawled in this session: {current_url}")
                    continue

                # Increment and update progress for this site BEFORE processing the page
                # This makes the progress bar smoother and updates for each page attempt
                pages_crawled_count += 1
                update_scraper_progress_for_site(site_id, pages_crawled_count, MAX_PAGES_PER_SITE, status='running') 

                print(f"  Crawling ({pages_crawled_count}/{MAX_PAGES_PER_SITE}): {current_url}")
                crawled_urls_for_site.add(current_url) # Mark this URL as crawled for the current session
                
                html_content = get_html(current_url)
                if not html_content:
                    print(f"    Failed to fetch HTML for {current_url}. Skipping processing and links extraction.")
                    time.sleep(CRAWL_DELAY)
                    continue

                article_data = extract_article_details_with_newspaper(current_url)

                if article_data and article_data['content'] and article_data['title'] != 'Título Não Encontrado':
                    found_terms_in_article = False
                    for term in search_terms:
                        # Perform case-insensitive search for terms in title and content
                        if term.lower() in article_data['content'].lower() or term.lower() in article_data['title'].lower():
                            add_article( # Add article to database
                                site_id=site_id,
                                title=article_data['title'],
                                url=article_data['url'],
                                content=article_data['content'],
                                published_date=article_data['published_date']
                            )
                            found_terms_in_article = True
                            break # Found a term, no need to check other terms for this article
                    if found_terms_in_article:
                        print(f"      Term found! Article saved: {article_data['title']} at {article_data['url']}")
                    else:
                        print(f"    No search terms found in article: {article_data['title']} (URL: {current_url})")
                else:
                    print(f"    Newspaper3k failed to extract meaningful content/title for {current_url}")

                # Find all internal links in the current page to continue crawling
                soup = BeautifulSoup(html_content, 'html.parser')
                for link_element in soup.find_all('a', href=True):
                    href = link_element.get('href')
                    full_url = urljoin(current_url, href)
                    parsed_full_url = urlparse(full_url)

                    # Criteria for following internal links:
                    # 1. The domain must match the base site's domain.
                    # 2. The URL must not have been crawled already in this session, nor be in the queue.
                    # 3. It should not be just a fragment (#).
                    # 4. It should not be a common media file (png, jpg, pdf, etc.).
                    # 5. It should not be a common navigation/admin/category path (can be refined).
                    if parsed_full_url.netloc == parsed_base_netloc and \
                       full_url not in crawled_urls_for_site and \
                       full_url not in to_crawl_urls and \
                       not full_url.startswith(current_url + '#') and \
                       not any(ext in parsed_full_url.path.lower() for ext in ['.png', '.jpg', '.gif', '.css', '.js', '.pdf', '.xml', '.rss', '.mp4', '.avi', '.zip']) and \
                       not any(kw in parsed_full_url.path.lower() or kw in parsed_full_url.query.lower() for kw in ['/category/', '/tag/', '/author/', '/feed/', '/wp-content/', '/wp-admin/', '/login', '/logout', '/register', '/search']):
                        
                        to_crawl_urls.append(full_url)
                        # print(f"    Added to queue: {full_url}") # Uncomment for debugging link additions
                
                time.sleep(CRAWL_DELAY) # Be polite to the server
            
            print(f"--- Finished crawling for site: {base_url}. Total pages crawled: {pages_crawled_count} ---\n")
        finally:
            # When the thread finishes (either by completing or stopping),
            # mark this specific site's progress as completed or stopped.
            # This is crucial for overall status aggregation.
            final_status = 'completed'
            if get_scraper_status()['status'] == 'stopped': # Check if global stop was issued
                final_status = 'stopped_by_user'
            
            update_scraper_progress_for_site(site_id, pages_crawled_count, MAX_PAGES_PER_SITE, status=final_status)
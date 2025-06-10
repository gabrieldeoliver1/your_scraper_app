import sqlite3
from flask import g
from datetime import datetime, timedelta

DATABASE = 'database.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def close_db(e=None):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE
            );
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS search_terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                term TEXT NOT NULL UNIQUE
            );
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                published_date TEXT,
                scraped_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (site_id) REFERENCES sites (id)
            );
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS site_scraping_progress (
                site_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'running',
                pages_crawled INTEGER DEFAULT 0,
                max_pages_to_crawl INTEGER DEFAULT 0,
                start_time TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (site_id) REFERENCES sites (id) ON DELETE CASCADE
            );
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scraper_control (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL DEFAULT 'stopped'
            );
        ''')
        cursor.execute("INSERT OR IGNORE INTO scraper_control (id, status) VALUES (1, 'stopped');")
        db.commit()
        cursor.close()

def add_site(url):
    with get_db() as db:
        cursor = db.cursor()
        try:
            cursor.execute('INSERT INTO sites (url) VALUES (?)', (url,))
            db.commit()
            return True
        except sqlite3.IntegrityError:
            print(f"Site already exists (ignored): {url}")
            return False
        finally:
            cursor.close()

def get_sites():
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute('SELECT * FROM sites')
        sites = cursor.fetchall()
        cursor.close()
        return [dict(site) for site in sites]

def delete_site(site_id):
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute('DELETE FROM sites WHERE id = ?', (site_id,))
        cursor.execute('DELETE FROM articles WHERE site_id = ?', (site_id,))
        cursor.execute('DELETE FROM site_scraping_progress WHERE site_id = ?', (site_id,))
        db.commit()
        cursor.close()

def add_search_term(term):
    with get_db() as db:
        cursor = db.cursor()
        try:
            cursor.execute('INSERT INTO search_terms (term) VALUES (?)', (term,))
            db.commit()
            return True
        except sqlite3.IntegrityError:
            print(f"Search term already exists (ignored): {term}")
            return False
        finally:
            cursor.close()

def get_search_terms():
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute('SELECT * FROM search_terms')
        terms = cursor.fetchall()
        cursor.close()
        return [dict(term) for term in terms]

def delete_search_term(term_id):
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute('DELETE FROM search_terms WHERE id = ?', (term_id,))
        db.commit()
        cursor.close()

def add_article(site_id, title, url, content, published_date):
    with get_db() as db:
        cursor = db.cursor()
        try:
            cursor.execute(
                'INSERT OR IGNORE INTO articles (site_id, title, url, content, published_date) VALUES (?, ?, ?, ?, ?)',
                (site_id, title, url, content, published_date)
            )
            db.commit()
        except sqlite3.IntegrityError:
            pass
        except Exception as e:
            print(f"Error adding article: {e}")
        finally:
            cursor.close()

# MODIFIED: get_articles now accepts page and per_page for pagination
def get_articles(query_terms=None, site_id=None, order_by='date_desc', start_date=None, end_date=None, page=1, per_page=10):
    with get_db() as db:
        cursor = db.cursor()
        
        # Base query for filtering
        base_sql_query = 'SELECT a.*, s.url as site_url FROM articles a JOIN sites s ON a.site_id = s.id WHERE 1=1'
        params = []

        if query_terms:
            term_clauses = []
            for term in query_terms:
                term_clauses.append('(a.title LIKE ? OR a.content LIKE ?)')
                params.append(f'%{term}%')
                params.append(f'%{term}%')
            if term_clauses:
                base_sql_query += ' AND (' + ' OR '.join(term_clauses) + ')'

        if site_id and site_id != 0:
            base_sql_query += ' AND a.site_id = ?'
            params.append(site_id)

        if start_date:
            base_sql_query += ' AND published_date >= ?'
            params.append(start_date)
        if end_date:
            try:
                end_date_dt = datetime.strptime(end_date, '%Y-%m-%d')
                next_day_str = (end_date_dt + timedelta(days=1)).strftime('%Y-%m-%d')
                base_sql_query += ' AND published_date < ?'
                params.append(next_day_str)
            except ValueError:
                base_sql_query += ' AND published_date <= ?'
                params.append(end_date)

        # First, get total count without LIMIT/OFFSET
        count_sql_query = f"SELECT COUNT(*) FROM ({base_sql_query}) AS subquery"
        cursor.execute(count_sql_query, params)
        total_results = cursor.fetchone()[0]

        # Apply ordering and pagination
        if order_by == 'date_desc':
            base_sql_query += ' ORDER BY a.published_date DESC, a.scraped_at DESC'
        elif order_by == 'date_asc':
            base_sql_query += ' ORDER BY a.published_date ASC, a.scraped_at ASC'
        
        # Calculate OFFSET
        offset = (page - 1) * per_page
        sql_query_paginated = f"{base_sql_query} LIMIT ? OFFSET ?"
        paginated_params = params + [per_page, offset]

        cursor.execute(sql_query_paginated, paginated_params)
        articles = cursor.fetchall()
        cursor.close()
        
        return {
            'articles': [dict(article) for article in articles],
            'total_results': total_results,
            'current_page': page,
            'per_page': per_page,
            'total_pages': (total_results + per_page - 1) // per_page if total_results > 0 else 0
        }

def update_scraper_progress_for_site(site_id, pages_crawled, max_pages_to_crawl, status='running'):
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute('INSERT OR REPLACE INTO site_scraping_progress (site_id, status, pages_crawled, max_pages_to_crawl) VALUES (?, ?, ?, ?)',
                       (site_id, status, pages_crawled, max_pages_to_crawl))
        db.commit()
        cursor.close()

def get_scraper_status():
    with get_db() as db:
        cursor = db.cursor()
        
        overall_status_row = cursor.execute('SELECT status FROM scraper_control WHERE id = 1').fetchone()
        overall_status = overall_status_row['status'] if overall_status_row else 'stopped'
        
        site_progresses = cursor.execute('SELECT site_id, status, pages_crawled, max_pages_to_crawl FROM site_scraping_progress').fetchall()
        
        total_pages_crawled = 0
        total_max_pages_to_crawl = 0
        active_sites_count = 0
        
        for p in site_progresses:
            if p['status'] == 'running':
                total_pages_crawled += p['pages_crawled']
                total_max_pages_to_crawl += p['max_pages_to_crawl']
                active_sites_count += 1
        
        if active_sites_count > 0:
            global_running_status = 'running'
        else:
            global_running_status = 'stopped'

        if overall_status != global_running_status:
            set_scraper_status(global_running_status)
            overall_status = global_running_status

        return {
            'status': overall_status,
            'pages_crawled': total_pages_crawled,
            'max_pages': total_max_pages_to_crawl,
            'individual_sites': [dict(p) for p in site_progresses]
        }

def set_scraper_status(status):
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute('UPDATE scraper_control SET status = ? WHERE id = 1', (status,))
        
        if status == 'stopped':
            cursor.execute('DELETE FROM site_scraping_progress')
        db.commit()
        cursor.close()

def import_sites_from_file(file_path):
    imported_count = 0
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            url = line.strip()
            if url:
                if add_site(url):
                    imported_count += 1
    return imported_count

def export_sites_to_file(file_path):
    sites = get_sites()
    with open(file_path, 'w', encoding='utf-8') as f:
        for site in sites:
            f.write(site['url'] + '\n')
    return len(sites)

def import_terms_from_file(file_path):
    imported_count = 0
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            term = line.strip()
            if term:
                if add_search_term(term):
                    imported_count += 1
    return imported_count

def export_terms_to_file(file_path):
    terms = get_search_terms()
    with open(file_path, 'w', encoding='utf-8') as f:
        for term in terms:
            f.write(term['term'] + '\n')
    return len(terms)
import threading
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file
from database import init_db, add_site, get_sites, get_articles, delete_site, \
                     add_search_term, get_search_terms, delete_search_term, \
                     set_scraper_status, get_scraper_status, \
                     import_sites_from_file, export_sites_to_file, \
                     import_terms_from_file, export_terms_to_file
from scraper import scrape_website_threaded, _crawled_urls_per_site_session
from datetime import datetime
import os

app = Flask(__name__)
app.config.from_object('config.Config')

UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

scraper_threads_list = []

with app.app_context():
    init_db()

@app.context_processor
def inject_datetime():
    return {'datetime': datetime}

@app.route('/')
def index():
    sites = get_sites()
    search_terms = get_search_terms()
    # Initial load, ensure pagination variables are present but defaults
    return render_template('index.html', sites=sites, search_terms=search_terms, articles=[],
                           selected_site_id=0, order_by='date_desc', start_date='', end_date='',
                           current_page=1, total_pages=0, total_results=0, per_page=10)

@app.route('/add_site', methods=['POST'])
def add_site_route():
    url = request.form['url'].strip()
    if url:
        add_site(url)
    return redirect(url_for('index'))

@app.route('/delete_site/<int:site_id>', methods=['POST'])
def delete_site_route(site_id):
    delete_site(site_id)
    return redirect(url_for('index'))

@app.route('/add_term', methods=['POST'])
def add_term_route():
    term = request.form['term'].strip()
    if term:
        add_search_term(term)
    return redirect(url_for('index'))

@app.route('/delete_term/<int:term_id>', methods=['POST'])
def delete_term_route(term_id):
    delete_search_term(term_id)
    return redirect(url_for('index'))

@app.route('/start_scrape', methods=['POST'])
def start_scrape_route():
    global scraper_threads_list
    
    _crawled_urls_per_site_session.clear() 

    active_threads = [t for t in scraper_threads_list if t.is_alive()]
    if active_threads:
        return jsonify({'status': 'Scraper já está rodando!'}), 200

    query_terms = [term['term'] for term in get_search_terms()]
    if not query_terms:
        return jsonify({'status': 'Erro: Adicione termos de busca antes de iniciar a varredura!'}), 400

    sites_to_process = get_sites()
    if not sites_to_process:
        return jsonify({'status': 'Erro: Nenhum site cadastrado para varrer. Adicione sites e termos de busca.'}), 400

    set_scraper_status('running')

    scraper_threads_list.clear()
    for site_info in sites_to_process:
        thread = threading.Thread(target=scrape_website_threaded, 
                                  args=(app.app_context(), site_info['id'], site_info['url'], query_terms))
        scraper_threads_list.append(thread)
        thread.start()
        
    if not scraper_threads_list:
        set_scraper_status('stopped')
        return jsonify({'status': 'Nenhum site para iniciar varredura.'}), 400

    return jsonify({'status': 'Scraper iniciado em background.'}), 202

@app.route('/stop_scrape', methods=['POST'])
def stop_scrape_route():
    set_scraper_status('stopped')
    return jsonify({'status': 'Comando de parada enviado ao scraper.'}), 202

@app.route('/scraper_status', methods=['GET'])
def scraper_status_route():
    status_info = get_scraper_status()
    
    global scraper_threads_list
    active_threads = [t for t in scraper_threads_list if t.is_alive()]
    
    if not active_threads and status_info['status'] == 'running':
        set_scraper_status('stopped')
        status_info = get_scraper_status()

    return jsonify({
        'status': status_info['status'].upper(),
        'pages_crawled': status_info['pages_crawled'],
        'max_pages': status_info['max_pages']
    })


@app.route('/search_articles', methods=['GET'])
def search_articles_route():
    sites = get_sites()
    search_terms_list_from_db = get_search_terms()
    query_terms = [term['term'] for term in search_terms_list_from_db]

    selected_site_id = request.args.get('site_id', type=int)
    order_by = request.args.get('order_by', 'date_desc')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # NEW: Pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int) # Default to 10 articles per page

    # get_articles now returns a dict with articles, total_results, etc.
    pagination_data = get_articles(query_terms, selected_site_id, order_by, start_date, end_date, page, per_page)
    articles = pagination_data['articles']
    total_results = pagination_data['total_results']
    current_page = pagination_data['current_page']
    total_pages = pagination_data['total_pages']
    
    return render_template('index.html', sites=sites, search_terms=search_terms_list_from_db,
                           articles=articles,
                           selected_site_id=selected_site_id,
                           order_by=order_by, start_date=start_date, end_date=end_date,
                           current_page=current_page, total_pages=total_pages, total_results=total_results, per_page=per_page)


@app.route('/import_sites', methods=['POST'])
def import_sites_route():
    if 'file' not in request.files:
        return jsonify({'status': 'Nenhum arquivo enviado'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'Nenhum arquivo selecionado'}), 400
    if file:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)
        try:
            imported_count = import_sites_from_file(file_path)
            os.remove(file_path)
            return jsonify({'status': f'{imported_count} sites importados com sucesso.', 'success': True}), 200
        except Exception as e:
            os.remove(file_path)
            return jsonify({'status': f'Erro ao importar sites: {str(e)}', 'success': False}), 500

@app.route('/export_sites', methods=['GET'])
def export_sites_route():
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'sites_export.txt')
        exported_count = export_sites_to_file(file_path)
        if exported_count > 0:
            return send_file(file_path, as_attachment=True, download_name='sites_export.txt', mimetype='text/plain')
        else:
            return jsonify({'status': 'Nenhum site para exportar.', 'success': False}), 404
    except Exception as e:
        return jsonify({'status': f'Erro ao exportar sites: {str(e)}', 'success': False}), 500

@app.route('/import_terms', methods=['POST'])
def import_terms_route():
    if 'file' not in request.files:
        return jsonify({'status': 'Nenhum arquivo enviado'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'Nenhum arquivo selecionado'}), 400
    if file:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)
        try:
            imported_count = import_terms_from_file(file_path)
            os.remove(file_path)
            return jsonify({'status': f'{imported_count} termos importados com sucesso.', 'success': True}), 200
        except Exception as e:
            os.remove(file_path)
            return jsonify({'status': f'Erro ao importar termos: {str(e)}', 'success': False}), 500

@app.route('/export_terms', methods=['GET'])
def export_terms_route():
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'terms_export.txt')
        exported_count = export_terms_to_file(file_path)
        if exported_count > 0:
            return send_file(file_path, as_attachment=True, download_name='terms_export.txt', mimetype='text/plain')
        else:
            return jsonify({'status': 'Nenhum termo para exportar.', 'success': False}), 404
    except Exception as e:
        return jsonify({'status': f'Erro ao exportar termos: {str(e)}', 'success': False}), 500

if __name__ == '__main__':
    app.run(debug=True, threaded=True)
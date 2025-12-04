from flask import Flask, render_template, request
import sqlite3
import os
import re
import html

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'articles.db')

def extract_text_from_html(html_content: str, max_length=200) -> str:
    """
    args:
        html_content: [str]
        max_length: [int]
    return:
        text: [str] 
    """
    text = re.sub(r'<[^>]+>', '', html_content)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_length]

def get_context_snippet(text: str, keyword: str, context_length=100) -> str:
    """
    args:
        text: [str]
        keyword: [str]
        context_length: [int]
    return:
        snippet: [str]
    """
    if not keyword or not text:
        return text[:context_length] + '...' if len(text) > context_length else text
    
    text_lower = text.lower()
    keyword_lower = keyword.lower()
    
    pos = text_lower.find(keyword_lower)
    if pos == -1:
        return text[:context_length] + '...' if len(text) > context_length else text
    
    start = max(0, pos - context_length // 2)
    end = min(len(text), pos + len(keyword) + context_length // 2)
    
    snippet = text[start:end]
    
    if start > 0:
        snippet = '...' + snippet
    if end < len(text):
        snippet = snippet + '...'
    
    snippet = re.sub(
        f'({re.escape(keyword)})',
        r'<mark>\1</mark>',
        snippet,
        flags=re.IGNORECASE
    )
    
    return snippet

def search_articles(keyword='', search_fields=None, page=1, per_page=10) -> tuple:
    """
    args:
        keyword: [str]
        search_fields: [list]
        page: [int]
        per_page: [int]
    return:
        articles, total: [tuple]
    """
    if search_fields is None:
        search_fields = ['title', 'author', 'category']
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    field_mapping = {
        'title': 'title',
        'author': 'author',
        'category': 'category',
        'content': 'content_html',
        'url': 'url'
    }
    
    conditions = []
    params = []
    
    if keyword:
        keywords = [k.strip() for k in keyword.split() if k.strip()]
        if keywords:
            keyword_conditions = []
            for kw in keywords:
                field_conditions = []
                for field in search_fields:
                    db_field = field_mapping.get(field, field)
                    field_conditions.append(f"{db_field} LIKE ?")
                    params.append(f'%{kw}%')
                if field_conditions:
                    keyword_conditions.append(f"({' OR '.join(field_conditions)})")
            if keyword_conditions:
                conditions.append(f"({' AND '.join(keyword_conditions)})")
    
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
    count_query = f'SELECT COUNT(*) FROM articles {where_clause}'
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]
    
    offset = (page - 1) * per_page
    query = f'''
    SELECT id, title, author, url, category, content_html, created_at
    FROM articles
    {where_clause}
    ORDER BY id DESC
    LIMIT ? OFFSET ?
    '''
    
    cursor.execute(query, params + [per_page, offset])
    results = cursor.fetchall()
    conn.close()
    
    articles = []
    
    keywords_list = [k.strip() for k in keyword.split() if k.strip()] if keyword else []
    
    for row in results:
        article_id, title, author, url, category, content_html, created_at = row
        snippet = ''
        if keywords_list:
            if 'content' in search_fields and content_html:
                text = extract_text_from_html(content_html, max_length=1000)
                snippet = get_context_snippet(text, keywords_list[0], context_length=80)
                for kw in keywords_list[1:]:
                    snippet = re.sub(
                        f'({re.escape(kw)})',
                        r'<mark>\1</mark>',
                        snippet,
                        flags=re.IGNORECASE
                    )
            else:
                matched_parts = []
                if 'title' in search_fields:
                    for kw in keywords_list:
                        if kw.lower() in title.lower():
                            matched_parts.append(f'标题: {title}')
                            break
                if 'author' in search_fields:
                    for kw in keywords_list:
                        if kw.lower() in author.lower():
                            matched_parts.append(f'作者: {author}')
                            break
                if 'category' in search_fields and category:
                    for kw in keywords_list:
                        if kw.lower() in category.lower():
                            matched_parts.append(f'目录: {category}')
                            break
                if matched_parts:
                    snippet = ' | '.join(matched_parts)
                else:
                    text = extract_text_from_html(content_html or '', max_length=200)
                    snippet = text + '...' if text else '无内容'
        
        articles.append({
            'id': article_id,
            'title': title,
            'author': author,
            'url': url,
            'category': category,
            'created_at': created_at,
            'snippet': snippet
        })
    
    return articles, total

@app.route('/')
def index():
    keyword = request.args.get('keyword', '').strip()
    search_fields = request.args.getlist('fields')
    page = int(request.args.get('page', 1))
    
    if not search_fields:
        search_fields = ['title', 'author', 'category']
    
    articles = []
    total = 0
    total_pages = 0
    
    if keyword:
        articles, total = search_articles(keyword, search_fields, page=page, per_page=10)
        total_pages = (total + 9) // 10  
    
    return render_template('index.html', 
                         articles=articles, 
                         keyword=keyword,
                         search_fields=search_fields,
                         page=page,
                         total=total,
                         total_pages=total_pages)

@app.route('/article/<int:article_id>')
def article_detail(article_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT id, title, author, url, category, content_html
    FROM articles
    WHERE id = ?
    ''', (article_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return "文章不存在", 404
    
    article = {
        'id': row[0],
        'title': row[1],
        'author': row[2],
        'url': row[3],
        'category': row[4],
        'content_html': row[5]
    }
    
    template_version = request.args.get('v', None)
    if template_version is None:
        template_version = '1' if article_id <= 16567 else '2'
    if template_version == '2':
        return render_template('article_v2.html', article=article)
    
    return render_template('article.html', article=article)

if __name__ == '__main__':
    app.run(debug=True, port=5002)

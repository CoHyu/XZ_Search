from playwright.sync_api import sync_playwright
import sqlite3
import time
import re
import os
import requests
import hashlib
import logging
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static', 'images')
os.makedirs(STATIC_DIR, exist_ok=True)
DB_PATH = os.path.join(BASE_DIR, 'articles.db')
log_file = os.path.join(BASE_DIR, f'scraperLogs/scraper_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

ARTICLE_VERSION_THRESHOLD = 16567

def setup_logger() -> logging.Logger:
    """
    args:
        None
    return:
        logger: [logging.Logger]
    """
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(handler)
    return logger

logger = setup_logger()

def article_exists(article_id: int) -> bool:
    """
    args:
        article_id: [int]
    return:
        exists: [bool]
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT 1 FROM articles WHERE id = ? LIMIT 1', (article_id,))
        return cursor.fetchone() is not None
    finally:
        conn.close()

def download_image(img_url: str) -> str:
    """
    args:
        img_url: [str]
    return:
        local_img_url: [str]
    """
    try:
        filename = hashlib.md5(img_url.encode()).hexdigest()
        ext = os.path.splitext(img_url.split('?')[0])[-1] or '.png'
        local_filename = filename + ext
        local_path = os.path.join(STATIC_DIR, local_filename)
        
        if os.path.exists(local_path):
            return f'/static/images/{local_filename}'
        
        resp = requests.get(img_url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://xz.aliyun.com/'
        })
        
        if resp.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(resp.content)
            return f'/static/images/{local_filename}'
    except Exception as e:
        logger.debug(f"图片下载失败: {img_url[:50]}... - {e}")
    
    return None

def process_images_in_html(html_content: str) -> str:
    """
    args:
        html_content: [str]
    return:
        processed_html: [str]
    """
    # <img class="img-fluid" src='https://example.com/images/pic1.png' alt="Picture 1" style="width: 100%;">
    # <img src="./local/assets/image.gif">
    def replace_img(match) -> str:
        img_tag = match.group(0)
        src_match = re.search(r'src=["\']([^"\']+)["\']', img_tag)
        
        if src_match:
            original_src = src_match.group(1)
            if original_src.startswith('http'):
                local_path = download_image(original_src)
                if local_path:
                    new_img_tag = img_tag.replace(original_src, local_path)
                    return new_img_tag
        return img_tag
    
    processed_html = re.sub(r'<img[^>]+>', replace_img, html_content)
    return processed_html

def save_article(article_data: dict) -> bool:
    """
    args:
        article_data: [dict]
    return:
        success: [bool]        
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
        INSERT OR REPLACE INTO articles (id, title, author, url, category, content_html)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            article_data['id'],
            article_data['title'],
            article_data['author'],
            article_data['url'],
            article_data['category'],
            article_data['content_html']
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"保存失败 (ID:{article_data.get('id')}): {e}")
        return False
    finally:
        conn.close()

def is_empty_article(title: str, article_id: int) -> bool:
    """
    args:
        title: [str]
        article_id: [int]
    return:
        is_empty: [bool]
    """
    return title == f'文章 {article_id}' or not title or title.strip() == ''

def scrape_single_article(article_id: int) -> dict:
    """
    args:
        article_id: [int]
    return:
        article_data: [dict]
    """
    if article_exists(article_id):
        logger.info(f"ID {article_id}: 已存在于数据库,跳过")
        return {'status': 'exists', 'id': article_id}
    
    url = f'https://xz.aliyun.com/news/{article_id}'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            if article_id <= ARTICLE_VERSION_THRESHOLD:
                page.goto(url, timeout=30000, wait_until='domcontentloaded')
                time.sleep(1.5)
                
                title_elem = page.query_selector('.detail_title')
                title = title_elem.inner_text().strip() if title_elem else f'文章 {article_id}'
                
                author_elem = page.query_selector('.username')
                author = author_elem.inner_text().strip() if author_elem else '未知作者'
                
                category_elem = page.query_selector('.cates_span')
                category = category_elem.inner_text().strip() if category_elem else ''
                
                content_elem = page.query_selector('.detail_content, #markdown-body')
                content_html = content_elem.inner_html() if content_elem else '<p>无内容</p>'
                
            else:
                logger.info(f"ID {article_id}: 检测到新版页面,执行滚动加载...")
                page.goto(url, timeout=60000, wait_until='domcontentloaded')
                page.evaluate("""
                    async () => {
                        await new Promise((resolve) => {
                            var totalHeight = 0;
                            var distance = 100;
                            var timer = setInterval(() => {
                                var scrollHeight = document.body.scrollHeight;
                                window.scrollBy(0, distance);
                                totalHeight += distance;

                                if(totalHeight >= scrollHeight){
                                    clearInterval(timer);
                                    resolve();
                                }
                            }, 50);
                        });
                    }
                """)
                time.sleep(2)
                
                page.evaluate("""
                    () => {
                        document.querySelectorAll('.ne-codeblock').forEach(el => {
                            el.style.display = 'block';
                        });
                        document.querySelectorAll('[style*="display: none"]').forEach(el => {
                            el.style.display = '';
                        });
                    }
                """)
                time.sleep(0.5)
                
                code_cards = page.query_selector_all('ne-card[data-card-name="codeblock"]')
                if code_cards:
                    logger.info(f"ID {article_id}: 发现 {len(code_cards)} 个代码块")
                
                time.sleep(1)
                
                title_elem = page.query_selector('.detail_title')
                title = title_elem.inner_text().strip() if title_elem else f'文章 {article_id}'
                
                author_elem = page.query_selector('.username')
                author = author_elem.inner_text().strip() if author_elem else '未知作者'
                
                category_elem = page.query_selector('.cates_span')
                category = category_elem.inner_text().strip() if category_elem else ''
                
                content_elem = page.query_selector('.ne-viewer-body')
                if not content_elem:
                    content_elem = page.query_selector('.detail_content, #markdown-body')
                
                if content_elem:
                    content_html = content_elem.inner_html()
                else:
                    content_html = '<p>无内容</p>'
                
                content_html = re.sub(
                    r'style="([^"]*?)display:\s*none;?([^"]*?)"',
                    lambda m: f'style="{m.group(1)}{m.group(2)}"'.replace('style=""', ''),
                    content_html
                )
                content_html = re.sub(r'\s*style=""', '', content_html)
            
            browser.close()
            
            if is_empty_article(title, article_id):
                return {'status': 'skip', 'id': article_id}
            
            content_html = process_images_in_html(content_html)
            
            article_data = {
                'status': 'success',
                'id': article_id,
                'title': title,
                'author': author,
                'url': url,
                'category': category,
                'content_html': content_html
            }
            
            return article_data
    except Exception as e:
        return {'status': 'error', 'id': article_id, 'error': str(e)}

def main(start_id=1, end_id=10, max_workers=5):
    print(f"Log_File: {log_file}")
    
    logger.info(f"{'='*60}")
    logger.info(f"Start from {start_id} to {end_id} (Processor_workers: {max_workers})")
    logger.info(f"DB_Path: {DB_PATH}")
    logger.info(f"Log_File: {log_file}")
    logger.info(f"{'='*60}")
    
    success_count = 0
    skip_count = 0
    fail_count = 0
    exists_count = 0
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {
            executor.submit(scrape_single_article, article_id): article_id 
            for article_id in range(start_id, end_id + 1)
        }
        
        for future in as_completed(future_to_id):
            article_id = future_to_id[future]
            try:
                result = future.result()
                
                if result['status'] == 'exists':
                    exists_count += 1
                elif result['status'] == 'skip':
                    logger.warning(f"ID {article_id}: blank, skipped")
                    skip_count += 1
                elif result['status'] == 'error':
                    logger.error(f"ID {article_id}: ERROR - {result.get('error', 'unkown error')}")
                    fail_count += 1
                elif result['status'] == 'success':
                    if save_article(result):
                        logger.info(f"ID {article_id}: {result['title'][:30]}...")
                        success_count += 1
                    else:
                        fail_count += 1
            except Exception as e:
                logger.error(f"ID {article_id}: - {e}")
                fail_count += 1
    
    logger.info(f"{'='*60}")
    logger.info(f"OK: {success_count} ")
    logger.info(f"EXISTS: {exists_count} (already in database)")
    logger.info(f"SKIP: {skip_count} (blank)")
    logger.info(f"ERROR: {fail_count} ")
    logger.info(f"{'='*60}")

if __name__ == '__main__':
    multiprocessing.freeze_support()
    # main(start_id=16500, end_id=16660, max_workers=3)
    # main(start_id=1, end_id=100, max_workers=3)
    main(start_id=90673, end_id=90738, max_workers=3)

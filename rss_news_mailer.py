import feedparser
import smtplib
import json
import os
import sys
import logging
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jinja2 import Environment, FileSystemLoader
import urllib.request
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'mail_config.json')
SOURCES_PATH = os.path.join(BASE_DIR, 'news_sources.json')
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(LOG_DIR, 'mailer.log'), encoding='utf-8'),
    ],
)
log = logging.getLogger('mail')

def load_config():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return json.load(f)

def load_sources():
    with open(SOURCES_PATH, encoding='utf-8') as f:
        return json.load(f)['sources']

def translate_to_jp(text):
    text = (text or '').strip()
    if not text:
        return ''
    url = 'https://api.mymemory.translated.net/get'
    for i in range(0, max(len(text), 1), 450):
        chunk = text[i:i+450]
        params = urllib.parse.urlencode({'q': chunk, 'langpair': 'en|ja'})
        req = urllib.request.Request(url + '?' + params)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data['responseStatus'] == 200:
                    return (data.get('responseData', {}).get('translatedText', '') or '').strip()
        except Exception as e:
            log.warning('Translation failed for chunk: %s', e)
    return ''

def translate_entries(entries):
    translated = []
    for entry in entries:
        title = entry.get('title', 'no title') or ''
        summary = entry.get('summary', '') or entry.get('description', '') or ''
        if any(chr(3000) in title or chr(0x4e00) <= c <= chr(0x9fff) for c in title):
            translated.append({'title': title, 'link': entry.get('link', '#'), 'published': entry.get('published', 'period unknown'), 'summary_jp': ''})
            continue
        j_title = translate_to_jp(title) if title else ''
        j_summary = translate_to_jp(summary) if summary else ''
        translated.append({'title': j_title or title, 'link': entry.get('link', '#'), 'published': entry.get('published', 'period unknown'), 'summary_jp': j_summary[:300]})
    return translated

def fetch_rss(source):
    try:
        log.info('Fetching: %s', source['name'])
        feed = feedparser.parse(source['url'])
        if feed.bozo:
            log.warning('bozo warning for %s: %s', source['name'], feed.bozo_exception)
        entries = []
        for item in feed.entries[:10]:
            published = item.get('published', 'period unknown')
            entries.append({'title': item.get('title', 'no title'), 'link': item.get('link', '#'), 'summary': item.get('summary', '') or item.get('description', ''), 'published': published})
        if source['name'] == 'TechCrunch AI':
            log.info('  Translating %d entries to Japanese...', len(entries))
            entries = translate_entries(entries)
        else:
            entries = [{'title': e['title'], 'link': e['link'], 'published': e['published']} for e in entries]
        log.info('  %d entries from %s', len(entries), source['name'])
        return {'name': source['name'], 'entries': entries}
    except Exception as e:
        log.error('Failed to fetch %s: %s', source['name'], e)
        return {'name': source['name'], 'entries': []}

def send_email(config, html_body):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'AI News - ' + datetime.now().strftime('%Y/%m/%d')
    msg['From'] = config['email_address']
    recipients = [config.get('recipient_address', config['email_address'])]
    msg['To'] = config['recipient_address']
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    with smtplib.SMTP(config['smtp_server'], config['smtp_port']) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(config['email_address'], config['app_password'])
        server.sendmail(config['email_address'], recipients, msg.as_string())
    log.info('Email sent to recipient')

def main():
    log.info('=' * 40)
    log.info('AI News Mailer started')
    config = load_config()
    if 'YOUR_EMAIL' in config['email_address']:
        log.error('Please set your email in mail_config.json')
        sys.exit(1)
    if 'YOUR_APP_PASSWORD' in config['app_password']:
        log.error('Please set your App Password in mail_config.json')
        sys.exit(1)
    sources = load_sources()
    results = []
    for src in sources:
        result = fetch_rss(src)
        if result['entries']:
            results.append(result)
    if not results:
        log.warning('No news found from any source.')
        return
    j2_dir = os.path.join(BASE_DIR, 'templates')
    env = Environment(loader=FileSystemLoader(j2_dir))
    template = env.get_template('daily.html.j2')
    html_body = template.render(sources=results, date=datetime.now().strftime('%Y年%m月%d日 (%a)'))
    send_email(config, html_body)
    log.info('Done.')

if __name__ == '__main__':
    main()

from flask import Flask, render_template, jsonify, request
import json
import os
import time
from datetime import datetime
from fetcher import fetch_all_trends, ECOMMERCE_KEYWORDS, CATEGORIES, get_category, search_custom_keyword, COUNTRIES
from nlp_processor import analyze_trend_nlp, compute_accuracy_score

app = Flask(__name__)

CACHE_FILE = "trend_cache.json"
CACHE_TTL = 3600  # 1 hour

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
        if time.time() - data.get('timestamp', 0) < CACHE_TTL:
            return data.get('trends', [])
    return None

def save_cache(trends):
    with open(CACHE_FILE, 'w') as f:
        json.dump({'timestamp': time.time(), 'trends': trends}, f)

def enrich_trends(raw_trends):
    """Add NLP analysis and accuracy scores to raw trend data."""
    enriched = []
    for t in raw_trends:
        nlp = analyze_trend_nlp(t['keyword'])
        accuracy = compute_accuracy_score(
            t['trend_score'], t['google_score'],
            t['social_score'], t['sentiment']
        )
        enriched.append({
            **t,
            'sentiment_label': nlp['sentiment_label'],
            'top_keywords': nlp['top_keywords'],
            'subjectivity': nlp['subjectivity'],
            'accuracy': accuracy,
            'accuracy_pct': round(accuracy * 100, 1),
            'trend_tag': get_trend_tag(t['trend_score']),
        })
    return enriched

def get_trend_tag(score):
    if score >= 80: return "🔥 Viral"
    if score >= 65: return "📈 Rising"
    if score >= 50: return "💡 Emerging"
    return "🔍 Watching"

def get_all_trends(force_refresh=False):
    if not force_refresh:
        cached = load_cache()
        if cached:
            return enrich_trends(cached)
    
    raw = fetch_all_trends()
    save_cache(raw)
    return enrich_trends(raw)

@app.route('/')
def index():
    trends = get_all_trends()
    top10 = trends[:10]
    avg_accuracy = round(sum(t['accuracy_pct'] for t in trends) / len(trends), 1)
    
    # Category breakdown
    cat_scores = {}
    for t in trends:
        cat = t['category']
        if cat not in cat_scores:
            cat_scores[cat] = []
        cat_scores[cat].append(t['trend_score'])
    cat_avg = {k: round(sum(v)/len(v), 1) for k, v in cat_scores.items()}
    
    return render_template('index.html',
        trends=top10,
        all_trends=trends,
        avg_accuracy=avg_accuracy,
        cat_avg=cat_avg,
        categories=list(CATEGORIES.keys()),
        updated_at=trends[0]['updated_at'] if trends else "N/A",
        total_count=len(trends)
    )

@app.route('/api/trends')
def api_trends():
    category = request.args.get('category', 'all')
    search = request.args.get('q', '').lower()
    sort_by = request.args.get('sort', 'trend_score')
    
    trends = get_all_trends()
    
    if category != 'all':
        trends = [t for t in trends if t['category'] == category]
    if search:
        trends = [t for t in trends if search in t['keyword'].lower()]
    
    valid_sorts = ['trend_score', 'google_score', 'social_score', 'accuracy_pct']
    if sort_by in valid_sorts:
        trends.sort(key=lambda x: x[sort_by], reverse=True)
    
    return jsonify(trends)

@app.route('/api/trend/<keyword>')
def api_trend_detail(keyword):
    trends = get_all_trends()
    match = next((t for t in trends if t['keyword'].lower() == keyword.lower()), None)
    if not match:
        return jsonify({'error': 'Keyword not found'}), 404
    return jsonify(match)

@app.route('/api/search_custom')
def api_search_custom():
    keyword = request.args.get('q', '').strip()
    if not keyword or len(keyword) < 2:
        return jsonify({'error': 'Please enter a valid product name'}), 400
    if len(keyword) > 100:
        return jsonify({'error': 'Keyword too long'}), 400

    try:
        result = search_custom_keyword(keyword)
        nlp = analyze_trend_nlp(keyword)
        accuracy = compute_accuracy_score(
            result['trend_score'], result['google_score'],
            result['social_score'], result['sentiment']
        )
        result['sentiment_label'] = nlp['sentiment_label']
        result['top_keywords'] = nlp['top_keywords']
        result['accuracy'] = accuracy
        result['accuracy_pct'] = round(accuracy * 100, 1)
        result['trend_tag'] = get_trend_tag(result['trend_score'])
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/refresh')
def api_refresh():
    trends = get_all_trends(force_refresh=True)
    return jsonify({'status': 'refreshed', 'count': len(trends)})

@app.route('/api/stats')
def api_stats():
    trends = get_all_trends()
    avg_accuracy = round(sum(t['accuracy_pct'] for t in trends) / len(trends), 1)
    viral_count = sum(1 for t in trends if t['trend_score'] >= 80)
    rising_count = sum(1 for t in trends if 65 <= t['trend_score'] < 80)
    
    return jsonify({
        'total': len(trends),
        'avg_accuracy': avg_accuracy,
        'viral_count': viral_count,
        'rising_count': rising_count,
        'top_trend': trends[0]['keyword'] if trends else None,
        'top_score': trends[0]['trend_score'] if trends else None,
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)

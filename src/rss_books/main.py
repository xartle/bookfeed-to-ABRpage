import requests
import re
import urllib.parse
import hashlib
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Dict, List, Any
from datetime import datetime, timedelta

# --- Configuration ---
RSS_FEED_URL = "https://bookfeed.io/feed/idAyKAmz8WOc-------------------urP5cAp20lcB49hNA0/feed.xml"
OUTPUT_HTML_FILE = "output.html"
ABR_SEARCH_URL = "http://yourservername:8788/search?q={title}&region=us"
LANGUAGE_FILTER = "en"
EXCLUDE_TITLES = ["No Title", "Untitled"]


def fetch_and_parse_feed():
    """Fetches the feed and parses book data from the plain text format."""
    print(f"Fetching feed from {RSS_FEED_URL}...")
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(RSS_FEED_URL, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL: {e}")
        return []

    print("Parsing feed content...")
    text = response.text
    books = []

    # Find the items array - it starts with "[items] => Array" and contains all books
    # We'll work with the text after this marker
    items_start = text.find('[items] => Array')
    if items_start == -1:
        print("Could not find items array")
        return []
    
    items_text = text[items_start:]
    
    # Split into individual book entries
    # Top-level books have exactly 12 spaces of indentation
    book_pattern = r'\n            \[\d+\] => stdClass Object\s*\('
    book_starts = [m.start() for m in re.finditer(book_pattern, items_text)]
    
    for i, start in enumerate(book_starts):
        # Extract text for this book (from this start to the next start, or end)
        if i + 1 < len(book_starts):
            book_text = items_text[start:book_starts[i + 1]]
        else:
            book_text = items_text[start:]
        
        # The volumeInfo section contains all the book metadata we need
        # We'll just use the entire book_text and extract fields directly from it
        vol_text = book_text
        
        # Extract fields
        book = {}
        
        # Title
        title_match = re.search(r'\[title\] => ([^\n]+)', vol_text)
        book['title'] = title_match.group(1).strip() if title_match else 'No Title'
        
        # Authors
        authors_match = re.search(r'\[authors\] => Array\s*\((.*?)\)', vol_text, re.DOTALL)
        if authors_match:
            author_text = authors_match.group(1)
            authors = re.findall(r'\[\d+\] => ([^\n]+)', author_text)
            book['authors'] = [a.strip() for a in authors]
        else:
            book['authors'] = []
        
        # Description
        desc_match = re.search(r'\[description\] => (.*?)\n\s*\[industryIdentifiers\]', vol_text, re.DOTALL)
        book['description'] = desc_match.group(1).strip() if desc_match else ''
        
        # Thumbnail
        thumb_match = re.search(r'\[thumbnail\] => (http[^\n]+)', vol_text)
        book['thumbnail'] = thumb_match.group(1).strip() if thumb_match else ''
        
        # Language
        lang_match = re.search(r'\[language\] => ([^\n]+)', vol_text)
        book['language'] = lang_match.group(1).strip() if lang_match else ''
        
        # Published Date
        date_match = re.search(r'\[publishedDate\] => ([^\n]+)', vol_text)
        book['publishedDate'] = date_match.group(1).strip() if date_match else ''
        
        # ISBN13
        isbn13_match = re.search(r'\[type\] => ISBN_13\s+\[identifier\] => ([^\n]+)', vol_text)
        book['isbn13'] = isbn13_match.group(1).strip() if isbn13_match else ''
        
        books.append(book)

    print(f"Found {len(books)} books")
    return books


# --- Deduplication Functions ---

def clean(s: str) -> str:
    """Clean string for comparison."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def strip_subtitle(title: str) -> str:
    """Strip subtitle from title."""
    if not title:
        return ""
    # split on colon or dash or parentheses hints like "(the expanse)"
    base = re.split(r":|\(|\u2013|\u2014|-", title, maxsplit=1)[0]
    return base.strip()


def strip_leading_articles(title: str) -> str:
    """Strip leading articles like 'The', 'A', 'An' from title."""
    if not title:
        return ""
    # Remove leading articles (case insensitive)
    title = title.strip()
    for article in ["The ", "A ", "An "]:
        if title.startswith(article):
            return title[len(article):]
    return title


def token_set_ratio(a: str, b: str) -> float:
    """Calculate token set ratio between two strings."""
    sa = set(clean(a).split())
    sb = set(clean(b).split())
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def token_sort_ratio(a: str, b: str) -> float:
    """Calculate token sort ratio between two strings."""
    aa = " ".join(sorted(clean(a).split()))
    bb = " ".join(sorted(clean(b).split()))
    return SequenceMatcher(None, aa, bb).ratio()


def short_fingerprint(text: str, n_words: int = 12) -> str:
    """Generate a short fingerprint from text."""
    if not text:
        return ""
    words = [w for w in clean(text).split() if len(w) > 3]
    top = words[:n_words]
    return hashlib.sha1(" ".join(top).encode("utf-8")).hexdigest()[:12]


def work_key(book: Dict[str, Any]) -> str:
    """Generate a work key from book data."""
    title = strip_subtitle(book.get("title", ""))
    title = strip_leading_articles(title)
    # Join authors list into a single string
    authors = book.get("authors", [])
    author = ", ".join(authors) if isinstance(authors, list) else str(authors)
    return f"{clean(title)}::{clean(author)}"


def similarity_score(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Calculate similarity score between two books."""
    # Compare stripped titles (without subtitles) for better matching
    title_a = strip_subtitle(a.get("title", ""))
    title_b = strip_subtitle(b.get("title", ""))
    t_title = token_set_ratio(title_a, title_b)
    
    # Handle author lists
    authors_a = a.get("authors", [])
    authors_b = b.get("authors", [])
    author_a = ", ".join(authors_a) if isinstance(authors_a, list) else str(authors_a)
    author_b = ", ".join(authors_b) if isinstance(authors_b, list) else str(authors_b)
    t_author = token_sort_ratio(author_a, author_b)
    
    desc_a = short_fingerprint(a.get("description", ""))
    desc_b = short_fingerprint(b.get("description", ""))
    # If either description is missing, don't penalize
    if not desc_a or not desc_b:
        desc_sim = 0.5  # Neutral score when description missing
    else:
        desc_sim = 1.0 if desc_a == desc_b else 0.0
    
    # Simplified weighted blend (no series data in our feed)
    score = 0.40 * t_title + 0.40 * t_author + 0.20 * desc_sim
    return score


def classify_pair(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    """Classify relationship between two books."""
    # Strong work match
    if work_key(a) == work_key(b):
        score = similarity_score(a, b)
        return "same_work" if score >= 0.65 else "uncertain"
    
    # Fuzzy rescue for mild title or author drift
    if token_set_ratio(a.get("title", ""), b.get("title", "")) >= 0.8:
        authors_a = a.get("authors", [])
        authors_b = b.get("authors", [])
        author_a = ", ".join(authors_a) if isinstance(authors_a, list) else str(authors_a)
        author_b = ", ".join(authors_b) if isinstance(authors_b, list) else str(authors_b)
        if token_sort_ratio(author_a, author_b) >= 0.9:
            return "same_work"
    
    return "different"


def dedupe_books(books: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate books by consolidating same work releases."""
    if not books:
        return books
    
    # Group by work key
    by_work = defaultdict(list)
    for idx, book in enumerate(books):
        wk = work_key(book)
        by_work[wk].append(idx)
    
    # For each work group, do pairwise comparison to find same works
    used = set()
    consolidated = []
    
    for book_idx, book in enumerate(books):
        if book_idx in used:
            continue
        
        # Find all books that match this one
        matching = [book_idx]
        for other_idx in range(book_idx + 1, len(books)):
            if other_idx in used:
                continue
            if classify_pair(book, books[other_idx]) == "same_work":
                matching.append(other_idx)
                used.add(other_idx)
        
        # Consolidate all matching books
        if len(matching) == 1:
            consolidated.append(book)
        else:
            # Merge multiple editions of the same work
            merged = consolidate_editions([books[i] for i in matching])
            consolidated.append(merged)
        
        used.add(book_idx)
    
    print(f"Deduplicated {len(books)} books down to {len(consolidated)} unique works")
    return consolidated


def consolidate_editions(editions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Consolidate multiple editions into a single entry, choosing the oldest real date."""
    # Start with the first edition as base
    merged = editions[0].copy()
    
    # Find the oldest real publication date
    dates = [e.get("publishedDate", "") for e in editions if e.get("publishedDate")]
    valid_dates = [d for d in dates if d and d != ""]
    if valid_dates:
        # Sort to find the oldest (earliest) date
        valid_dates.sort()
        merged["publishedDate"] = valid_dates[0]
    
    # Use the longest description
    descriptions = [e.get("description", "") for e in editions]
    longest_desc = max(descriptions, key=len) if descriptions else ""
    merged["description"] = longest_desc
    
    # Prefer entries with thumbnails
    for edition in editions:
        if edition.get("thumbnail"):
            merged["thumbnail"] = edition["thumbnail"]
            break
    
    # Track merged editions for display (with ISBN13)
    if len(editions) > 1:
        merged["_merged_editions"] = [
            {"title": e.get("title", "Unknown"), "isbn13": e.get("isbn13", "")}
            for e in editions
        ]
    
    return merged


def generate_html(books):
    """Generates HTML page from book data."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Book Feed</title>
    <style>
        body { font-family: sans-serif; margin: 2em; }
        .book { border-bottom: 1px solid #ccc; padding: 1em 0; overflow: hidden; position: relative; }
        .book img { float: left; margin-right: 1em; max-width: 100px; }
        .book h2 { font-size: 1.2em; margin: 0 0 0.5em 0; }
        .book p { margin: 0.3em 0; }
        .clear { clear: both; }
        details { margin: 0.5em 0; font-size: 0.9em; }
        details summary { cursor: pointer; color: #666; }
        details ul { margin: 0.5em 0; padding-left: 1.5em; list-style-type: none; }
        details li { margin: 0.3em 0; }
        .isbn { color: #888; font-size: 0.85em; font-family: monospace; }
        /* Recent release highlighting */
        .book.recent { background: linear-gradient(to right, #fffacd 0%, #ffffff 100%); border-left: 4px solid #ffd700; padding-left: 1em; }
        .new-badge { display: inline-block; background: #ffd700; color: #000; font-size: 0.7em; font-weight: bold; padding: 0.2em 0.5em; border-radius: 3px; margin-left: 0.5em; vertical-align: middle; }
    </style>
</head>
<body>
    <h1>Book Feed</h1>
"""

    # Filter books first
    filtered_books = []
    filtered = 0
    
    for book in books:
        # Apply filters
        if book.get('language') != LANGUAGE_FILTER or book.get('title') in EXCLUDE_TITLES:
            filtered += 1
            continue
        filtered_books.append(book)
    
    # Sort by published date, newest first (descending order)
    # Books without dates go to the end
    filtered_books.sort(key=lambda b: b.get('publishedDate', ''), reverse=True)
    
    included = 0
    
    # Calculate date threshold for "recent" releases (last 30 days)
    today = datetime.now()
    one_month_ago = today - timedelta(days=30)
    
    for book in filtered_books:
        included += 1
        title = book.get('title', 'No Title')
        authors = ', '.join(book.get('authors', ['Unknown Author']))
        description = book.get('description', 'No description available.')
        thumbnail = book.get('thumbnail', '')
        pub_date = book.get('publishedDate', '')
        
        search_url = ABR_SEARCH_URL.format(title=urllib.parse.quote_plus(title))
        
        # Check if this is a recent release (last 30 days, not future)
        is_recent = False
        pub_date_str = book.get('publishedDate', '')
        if pub_date_str:
            try:
                # Try parsing different date formats
                for fmt in ['%Y-%m-%d', '%Y-%m', '%Y']:
                    try:
                        pub_date_obj = datetime.strptime(pub_date_str, fmt)
                        # Only mark as recent if between one month ago and today (not future)
                        if one_month_ago <= pub_date_obj <= today:
                            is_recent = True
                        break
                    except ValueError:
                        continue
            except:
                pass
        
        recent_class = " recent" if is_recent else ""
        new_badge = '<span class="new-badge">NEW</span>' if is_recent else ""
        
        # Check if this is a merged entry
        merged_editions = book.get('_merged_editions', [])
        merged_note = ""
        if merged_editions:
            editions_list = []
            for ed in merged_editions:
                if isinstance(ed, dict):
                    title = ed.get('title', 'Unknown')
                    isbn = ed.get('isbn13', '')
                    if isbn:
                        editions_list.append(f'                <li>{title} <span class="isbn">ISBN: {isbn}</span></li>')
                    else:
                        editions_list.append(f'                <li>{title}</li>')
                else:
                    # Fallback for old format
                    editions_list.append(f'                <li>{ed}</li>')
            editions_list_html = "\n".join(editions_list)
            merged_note = f"""
        <details>
            <summary><em>Multiple editions merged ({len(merged_editions)} editions)</em></summary>
            <ul>
{editions_list_html}
            </ul>
        </details>"""
        
        html += f"""    <div class="book{recent_class}">
        <img src="{thumbnail}" alt="{title}">
        <h2>{title}{new_badge}</h2>
        <p><strong>Author:</strong> {authors}</p>
        <p><strong>Published:</strong> {pub_date}</p>
        <p><a href="{search_url}" target="_blank">Search on ABR</a></p>{merged_note}
        <p>{description}</p>
        <div class="clear"></div>
    </div>
"""

    html += """</body>
</html>
"""

    print(f"Included {included} books")
    print(f"Filtered out {filtered} books")
    return html


def main():
    """Main entry point."""
    books = fetch_and_parse_feed()
    
    if not books:
        print("No books found. Exiting.")
        return
    
    # Deduplicate books by consolidating same work releases
    books = dedupe_books(books)
    
    html = generate_html(books)
    
    try:
        with open(OUTPUT_HTML_FILE, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Successfully generated {OUTPUT_HTML_FILE}")
    except IOError as e:
        print(f"Error writing file: {e}")


if __name__ == "__main__":
    main()

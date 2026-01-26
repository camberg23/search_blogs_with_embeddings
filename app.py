# blog_search.py
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI
import json
import re
import time
from secret_keys import *

st.set_page_config(page_title="Truity Blog Search", page_icon="🔍", layout="wide")

def create_connection():
    conn = psycopg2.connect(
        host=SUPABASE_HOST,
        port="5432",
        user="postgres.unspmmribsqbeuzhenmv",
        password=SUPABASE_PASSWORD,
        dbname="postgres",
        sslmode="require"
    )
    return conn

def get_embedding(text, client):
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

def get_blogs_needing_embeddings(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('''
            SELECT b.url, b.title, b.text, b.categories, b.rss_content, b.date
            FROM blogs b
            LEFT JOIN blogs_embeddings be ON b.url = be.url
            WHERE be.url IS NULL OR be.embedding IS NULL
        ''')
        return cursor.fetchall()

def insert_blog_with_embedding(conn, blog_data, embedding):
    embedding_str = '[' + ','.join(f'{x:.8f}' for x in embedding) + ']'
    with conn.cursor() as cursor:
        cursor.execute('''
            INSERT INTO blogs_embeddings (url, rss_content, categories, title, text, date, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
            ON CONFLICT (url) DO UPDATE SET
                rss_content = EXCLUDED.rss_content,
                categories = EXCLUDED.categories,
                title = EXCLUDED.title,
                text = EXCLUDED.text,
                date = EXCLUDED.date,
                embedding = EXCLUDED.embedding
        ''', (
            blog_data['url'],
            blog_data['rss_content'],
            blog_data['categories'],
            blog_data['title'],
            blog_data['text'],
            blog_data['date'],
            embedding_str
        ))
    conn.commit()

def sync_embeddings(conn, client):
    blogs_needing_embeddings = get_blogs_needing_embeddings(conn)
    
    if not blogs_needing_embeddings:
        return 0
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    successful = 0
    for idx, blog in enumerate(blogs_needing_embeddings):
        try:
            status_text.text(f"Generating embeddings... ({idx + 1}/{len(blogs_needing_embeddings)})")
            
            text_to_embed = f"{blog['title']}\n\n{blog['text']}"
            max_chars = 8000
            if len(text_to_embed) > max_chars:
                text_to_embed = text_to_embed[:max_chars]
            
            embedding = get_embedding(text_to_embed, client)
            insert_blog_with_embedding(conn, blog, embedding)
            
            successful += 1
            progress_bar.progress((idx + 1) / len(blogs_needing_embeddings))
            
            if idx < len(blogs_needing_embeddings) - 1:
                time.sleep(0.2)
                
        except Exception as e:
            st.error(f"Failed to process '{blog['title'][:50]}...': {e}")
            continue
    
    progress_bar.empty()
    status_text.empty()
    
    return successful

def detect_personality_types(query):
    query_upper = query.upper()
    
    mbti_types = ['INTJ', 'INTP', 'ENTJ', 'ENTP', 'INFJ', 'INFP', 'ENFJ', 'ENFP',
                  'ISTJ', 'ISFJ', 'ESTJ', 'ESFJ', 'ISTP', 'ISFP', 'ESTP', 'ESFP']
    detected_mbti = [t for t in mbti_types if t in query_upper]
    
    enneagram_patterns = [
        r'TYPE\s*(\d|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE)',
        r'ENNEAGRAM\s*(\d|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE)'
    ]
    detected_enneagram = []
    for pattern in enneagram_patterns:
        matches = re.findall(pattern, query_upper)
        detected_enneagram.extend(matches)
    
    return detected_mbti, detected_enneagram

def extract_author_from_rss(rss_content):
    if not rss_content:
        return None
    
    match = re.search(r'<dc:creator><!\[CDATA\[(.*?)\]\]></dc:creator>', rss_content)
    if match:
        return match.group(1)
    
    match = re.search(r'<dc:creator>(.*?)</dc:creator>', rss_content)
    if match:
        return match.group(1)
    
    match = re.search(r'<author>(.*?)</author>', rss_content)
    if match:
        return match.group(1)
    
    return None

def hybrid_search(conn, search_query, query_embedding, limit=10, type_filter=None):
    """
    Hybrid search combining keyword matching and semantic similarity.
    Keyword matches are prioritized, then semantic matches fill the rest.
    """
    embedding_str = '[' + ','.join(f'{x:.8f}' for x in query_embedding) + ']'
    
    # Step 1: Get keyword matches (exact phrase in title or text)
    keyword_results = []
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SET enable_indexscan = off")
        cursor.execute("SET enable_bitmapscan = off")
        
        keyword_query = '''
            SELECT 
                url,
                title,
                text,
                categories,
                date,
                rss_content,
                1.0 as similarity,
                'keyword' as match_type
            FROM blogs_embeddings
            WHERE embedding IS NOT NULL
            AND (title ILIKE %s OR text ILIKE %s)
        '''
        
        params = [f'%{search_query}%', f'%{search_query}%']
        
        if type_filter:
            keyword_query += ' AND (title ILIKE %s OR text ILIKE %s OR categories ILIKE %s)'
            params.extend([f'%{type_filter}%', f'%{type_filter}%', f'%{type_filter}%'])
        
        keyword_query += ' ORDER BY date DESC LIMIT %s'
        params.append(limit)
        
        cursor.execute(keyword_query, params)
        keyword_results = cursor.fetchall()
    
    # Step 2: Get semantic matches
    semantic_results = []
    urls_to_exclude = [r['url'] for r in keyword_results]
    
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SET enable_indexscan = off")
        cursor.execute("SET enable_bitmapscan = off")
        
        if type_filter:
            semantic_query = f'''
                SELECT 
                    url,
                    title,
                    text,
                    categories,
                    date,
                    rss_content,
                    1 - (embedding <=> '{embedding_str}'::vector) as similarity,
                    'semantic' as match_type
                FROM blogs_embeddings
                WHERE embedding IS NOT NULL
                AND url != ALL(%s)
                AND (title ILIKE %s OR text ILIKE %s OR categories ILIKE %s)
                ORDER BY embedding <=> '{embedding_str}'::vector
                LIMIT {int(limit)}
            '''
            cursor.execute(semantic_query, (urls_to_exclude, f'%{type_filter}%', f'%{type_filter}%', f'%{type_filter}%'))
        else:
            semantic_query = f'''
                SELECT 
                    url,
                    title,
                    text,
                    categories,
                    date,
                    rss_content,
                    1 - (embedding <=> '{embedding_str}'::vector) as similarity,
                    'semantic' as match_type
                FROM blogs_embeddings
                WHERE embedding IS NOT NULL
                AND url != ALL(%s)
                ORDER BY embedding <=> '{embedding_str}'::vector
                LIMIT {int(limit)}
            '''
            cursor.execute(semantic_query, (urls_to_exclude,))
        
        semantic_results = cursor.fetchall()
    
    # Step 3: Combine results (keyword matches first, then semantic)
    combined_results = keyword_results + semantic_results
    
    # Limit to requested number
    return combined_results[:limit]

def get_stats(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('''
            SELECT 
                COUNT(*) as total_blogs,
                COUNT(embedding) as blogs_with_embeddings
            FROM blogs_embeddings
        ''')
        return cursor.fetchone()

def generate_gap_analysis(client, search_query, results, conn, type_filter=None):
    """
    Multi-step gap analysis that researches existing blog coverage first.
    """
    
    # Step 1: If searching for a specific type, find what topics OTHER types have covered
    comparative_analysis = ""
    if type_filter:
        # Get all MBTI types
        all_types = ['INTJ', 'INTP', 'ENTJ', 'ENTP', 'INFJ', 'INFP', 'ENFJ', 'ENFP',
                     'ISTJ', 'ISFJ', 'ESTJ', 'ESFJ', 'ISTP', 'ISFP', 'ESTP', 'ESFP']
        
        # Find topics covered for other types
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Get sample of articles for other similar types
            other_types = [t for t in all_types if t != type_filter][:4]  # Compare to 4 similar types
            
            other_type_articles = []
            for other_type in other_types:
                cursor.execute('''
                    SELECT title, categories
                    FROM blogs_embeddings
                    WHERE embedding IS NOT NULL
                    AND (title ILIKE %s OR text ILIKE %s)
                    ORDER BY date DESC
                    LIMIT 10
                ''', (f'%{other_type}%', f'%{other_type}%'))
                
                articles = cursor.fetchall()
                if articles:
                    other_type_articles.append({
                        'type': other_type,
                        'titles': [a['title'] for a in articles]
                    })
            
            if other_type_articles:
                comparative_analysis = "TOPICS COVERED FOR SIMILAR TYPES:\n"
                for type_data in other_type_articles:
                    comparative_analysis += f"\n{type_data['type']}:\n"
                    for title in type_data['titles'][:5]:
                        comparative_analysis += f"  - {title}\n"
    
    # Step 2: Analyze what broad topic categories exist in our results
    existing_titles = [r['title'] for r in results]
    existing_titles_str = "\n".join(f"- {t}" for t in existing_titles)
    
    # Step 3: Get broader context - what else exists in our blog for this general search area
    broader_context = ""
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        # Extract key terms from search query (remove common words)
        search_terms = [word for word in search_query.lower().split() 
                       if word not in ['the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for']]
        
        if search_terms:
            # Search for related articles using key terms
            term_query = ' OR '.join([f"title ILIKE '%{term}%'" for term in search_terms[:3]])
            cursor.execute(f'''
                SELECT title, categories
                FROM blogs_embeddings
                WHERE embedding IS NOT NULL
                AND ({term_query})
                ORDER BY date DESC
                LIMIT 30
            ''')
            
            broader_articles = cursor.fetchall()
            if broader_articles:
                broader_context = f"\n\nBROADER CONTEXT - Related articles in our blog ({len(broader_articles)} found):\n"
                for article in broader_articles[:15]:
                    broader_context += f"  - {article['title']}\n"
    
    # Step 4: Generate gap analysis with all this context
    prompt = f"""You are analyzing content gaps in a personality psychology blog.

SEARCH QUERY: "{search_query}"

YOUR TOP SEARCH RESULTS:
{existing_titles_str}

{comparative_analysis}

{broader_context}

TASK: Suggest 4-6 specific article ideas that fill real gaps in our content.

PROCESS:
1. First, identify broad topic areas that appear for similar searches or types but are underrepresented in the top results
2. Look for patterns - what angles do we cover repeatedly vs. what's missing?
3. Generate specific, practical titles that address the gaps

REQUIREMENTS:
- Be SPECIFIC and PRACTICAL (not generic like "ENTP as a Parent")
- Use NATURAL, conversational language (avoid AI phrases like "Unlocking", "Journey", "Navigate")
- Base suggestions on actual gaps you see in the content analysis above
- Each title should address a concrete question or problem

FORMAT:
**[Specific, natural title]**
Gap filled: [One sentence explaining what's missing that this addresses]

GOOD EXAMPLES:
- "Why ENTPs Abandon New Hobbies After Two Weeks (And How to Actually Stick With One)"
  Gap filled: We cover ENTP strengths but not this specific behavioral pattern many experience

- "What to Do When Your INFJ Partner Needs Alone Time (A Practical Guide for Extroverts)"
  Gap filled: We discuss INFJ traits but not concrete advice for partners navigating this

BAD EXAMPLES (too generic/AI-sounding):
- "ENTP Parenting: A Complete Guide"
- "Unlocking Your ENTP Potential in Relationships"
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "You are a content strategist who analyzes content gaps based on actual data, not just imagination. You write in a natural, specific style."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
    )
    
    return response.choices[0].message.content
    
# Initialize connection and client
if 'conn' not in st.session_state:
    st.session_state.conn = create_connection()
if 'openai_client' not in st.session_state:
    st.session_state.openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Auto-sync embeddings on app load
if 'embeddings_synced' not in st.session_state:
    with st.spinner("Checking for new blogs..."):
        blogs_needing_embeddings = get_blogs_needing_embeddings(st.session_state.conn)
        if blogs_needing_embeddings:
            st.info(f"Found {len(blogs_needing_embeddings)} new blogs. Generating embeddings...")
            synced_count = sync_embeddings(st.session_state.conn, st.session_state.openai_client)
            if synced_count > 0:
                st.success(f"✅ Generated embeddings for {synced_count} new blogs!")
                time.sleep(2)
                st.rerun()
    st.session_state.embeddings_synced = True

st.title("🔍 Truity Blog Search")
st.markdown("**Hybrid search** combines keyword matching with semantic search for comprehensive results.")

with st.sidebar:
    st.header("📊 Database Status")
    stats = get_stats(st.session_state.conn)
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Blogs", stats['total_blogs'])
    with col2:
        st.metric("With Embeddings", stats['blogs_with_embeddings'])
    
    if stats['blogs_with_embeddings'] == 0:
        st.warning("No embeddings yet!")
    else:
        st.success(f"{stats['blogs_with_embeddings']} blogs searchable")
    
    st.divider()
    st.markdown("**💡 How It Works:**")
    st.markdown("• **Keyword matches** appear first (exact phrase in title/text)")
    st.markdown("• **Semantic matches** fill the rest (similar meaning)")
    st.markdown("• This ensures you never miss directly relevant content")

st.header("Search")

search_query = st.text_input(
    "What are you looking for?",
    placeholder="e.g., 'age gap relationships' or 'meditation for anxiety'",
    key="search_input"
)

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    num_results = st.slider("Number of results", 1, 20, 10)
with col2:
    show_summaries = st.checkbox("Generate summaries", value=False)
with col3:
    show_gap_analysis = st.checkbox("Show content gaps", value=False)

if st.button("Search", type="primary") and search_query:
    stats = get_stats(st.session_state.conn)
    if stats['blogs_with_embeddings'] == 0:
        st.error("No embeddings available.")
    else:
        with st.spinner("Searching..."):
            detected_mbti, detected_enneagram = detect_personality_types(search_query)
            
            type_filter = None
            if detected_mbti:
                type_filter = detected_mbti[0]
                st.info(f"🎯 Filtering results to include '{type_filter}' content")
            elif detected_enneagram:
                type_filter = f"Type {detected_enneagram[0]}" if detected_enneagram[0].isdigit() else detected_enneagram[0]
                st.info(f"🎯 Filtering results to include '{type_filter}' content")
            
            query_embedding = get_embedding(search_query, st.session_state.openai_client)
            results = hybrid_search(st.session_state.conn, search_query, query_embedding, limit=num_results, type_filter=type_filter)
            
            if results:
                # Count match types
                keyword_count = sum(1 for r in results if r.get('match_type') == 'keyword')
                semantic_count = sum(1 for r in results if r.get('match_type') == 'semantic')
                
                st.success(f"Found {len(results)} articles ({keyword_count} keyword matches, {semantic_count} semantic matches)")
                
                for idx, result in enumerate(results, 1):
                    author = extract_author_from_rss(result.get('rss_content'))
                    match_type = result.get('match_type', 'semantic')
                    
                    # Add badge for keyword matches
                    title_display = result['title']
                    if match_type == 'keyword':
                        title_display = f"🎯 {title_display}"
                    
                    with st.expander(f"**{idx}. {title_display}**", expanded=True):
                        col1, col2, col3 = st.columns([2, 1, 1])
                        with col1:
                            if match_type == 'keyword':
                                st.markdown(f"**Match Type:** Keyword (exact match)")
                            else:
                                st.markdown(f"**Similarity Score:** {result['similarity']:.1%}")
                        with col2:
                            if result['date']:
                                st.markdown(f"**Date:** {result['date']}")
                        with col3:
                            if author:
                                st.markdown(f"**Author:** {author}")
                        
                        st.markdown(f"[View Article →]({result['url']})")
                        
                        try:
                            categories = json.loads(result['categories'])
                            if categories:
                                st.markdown(f"**Categories:** {', '.join(categories)}")
                        except:
                            pass
                        
                        if show_summaries and result['text']:
                            with st.spinner("Generating summary..."):
                                try:
                                    summary_response = st.session_state.openai_client.chat.completions.create(
                                        model="gpt-4o-mini",
                                        messages=[
                                            {"role": "system", "content": "Summarize this blog post in 2-3 sentences, focusing on key points."},
                                            {"role": "user", "content": f"Title: {result['title']}\n\nContent: {result['text'][:1500]}"}
                                        ],
                                    )
                                    st.markdown(f"**Summary:** {summary_response.choices[0].message.content}")
                                except Exception as e:
                                    st.warning(f"Could not generate summary: {e}")
                
                if show_gap_analysis:
                    st.divider()
                    st.subheader("💡 Suggested Topics We Haven't Covered Yet")
                    with st.spinner("Analyzing content gaps..."):
                        try:
                            gap_ideas = generate_gap_analysis(
                                                                st.session_state.openai_client, 
                                                                search_query, 
                                                                results, 
                                                                st.session_state.conn,
                                                                type_filter
                                                            )
                            st.markdown(gap_ideas)
                        except Exception as e:
                            st.warning(f"Could not generate gap analysis: {e}")
            else:
                st.warning("No articles found. Try a different search.")

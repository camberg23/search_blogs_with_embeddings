# blog_search.py
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
from openai import OpenAI
import json
from secret_keys import *
import re
import time

load_dotenv()

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
    """Get blogs that need embeddings."""
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('''
            SELECT b.url, b.title, b.text, b.categories, b.rss_content, b.date
            FROM blogs b
            LEFT JOIN blogs_embeddings be ON b.url = be.url
            WHERE be.url IS NULL OR be.embedding IS NULL
        ''')
        return cursor.fetchall()

def insert_blog_with_embedding(conn, blog_data, embedding):
    """Insert or update a blog in blogs_embeddings with its embedding."""
    embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
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
    """Check for new blogs and generate embeddings if needed."""
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
    """Detect MBTI and Enneagram types in the query."""
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
    """Extract author name from RSS content."""
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

def search_similar_blogs(conn, query_embedding, limit=10, type_filter=None):
    # Convert embedding to PostgreSQL vector string format
    embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'
    
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        if type_filter:
            query = f'''
                SELECT 
                    url,
                    title,
                    text,
                    categories,
                    date,
                    rss_content,
                    1 - (embedding <=> '{embedding_str}'::vector) as similarity
                FROM blogs_embeddings
                WHERE embedding IS NOT NULL
                AND (title ILIKE %s OR text ILIKE %s OR categories ILIKE %s)
                ORDER BY embedding <=> '{embedding_str}'::vector
                LIMIT {int(limit)}
            '''
            cursor.execute(query, (f'%{type_filter}%', f'%{type_filter}%', f'%{type_filter}%'))
        else:
            query = f'''
                SELECT 
                    url,
                    title,
                    text,
                    categories,
                    date,
                    rss_content,
                    1 - (embedding <=> '{embedding_str}'::vector) as similarity
                FROM blogs_embeddings
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> '{embedding_str}'::vector
                LIMIT {int(limit)}
            '''
            cursor.execute(query)
        return cursor.fetchall()

def get_stats(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('''
            SELECT 
                COUNT(*) as total_blogs,
                COUNT(embedding) as blogs_with_embeddings
            FROM blogs_embeddings
        ''')
        return cursor.fetchone()

def generate_gap_analysis(client, search_query, results):
    """Generate content gap analysis and new article ideas."""
    existing_titles = [r['title'] for r in results]
    existing_titles_str = "\n".join(f"- {t}" for t in existing_titles)
    
    prompt = f"""Based on the search query "{search_query}", here are the existing blog articles we have:

{existing_titles_str}

Please suggest 4-6 new article ideas that would fill gaps in our content coverage for this topic. These should be topics we haven't covered yet but would be valuable for readers interested in "{search_query}".

Format each suggestion as a potential article title, with a brief (1 sentence) explanation of why it would be valuable.

Focus on:
- Angles we haven't explored
- Related subtopics missing from our coverage
- Fresh perspectives on the topic
- Practical applications we haven't addressed"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a content strategist helping identify gaps in a personality psychology blog's content. Suggest practical, engaging article ideas that would complement existing coverage."},
            {"role": "user", "content": prompt}
        ],
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
st.markdown("**Semantic search** finds blog content by meaning, not keywords. The more specific your query, the better the results.")

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
    st.markdown("**💡 Search Tips:**")
    st.markdown("• Be specific and descriptive")
    st.markdown("• Use complete phrases or sentences")
    st.markdown("• Example: *'mindfulness meditation techniques for anxiety'* is better than just *'meditation'*")

st.header("Search")

search_query = st.text_input(
    "Describe what you're looking for (be specific for best results)",
    placeholder="e.g., 'articles about meditation techniques for reducing anxiety' or 'INFJ relationship compatibility advice'",
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
            results = search_similar_blogs(st.session_state.conn, query_embedding, limit=num_results, type_filter=type_filter)
            
            if results:
                st.success(f"Showing {len(results)} most similar articles")
                
                for idx, result in enumerate(results, 1):
                    author = extract_author_from_rss(result.get('rss_content'))
                    
                    with st.expander(f"**{idx}. {result['title']}**", expanded=True):
                        col1, col2, col3 = st.columns([2, 1, 1])
                        with col1:
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
                            gap_ideas = generate_gap_analysis(st.session_state.openai_client, search_query, results)
                            st.markdown(gap_ideas)
                        except Exception as e:
                            st.warning(f"Could not generate gap analysis: {e}")
            else:
                st.warning(f"No articles found. Try a different search.")
openai

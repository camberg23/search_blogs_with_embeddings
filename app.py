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

def detect_personality_types(query):
    """Detect MBTI and Enneagram types in the query."""
    query_upper = query.upper()
    
    # MBTI types
    mbti_types = ['INTJ', 'INTP', 'ENTJ', 'ENTP', 'INFJ', 'INFP', 'ENFJ', 'ENFP',
                  'ISTJ', 'ISFJ', 'ESTJ', 'ESFJ', 'ISTP', 'ISFP', 'ESTP', 'ESFP']
    detected_mbti = [t for t in mbti_types if t in query_upper]
    
    # Enneagram types (looking for "TYPE 1", "TYPE ONE", "ENNEAGRAM 1", etc.)
    enneagram_patterns = [
        r'TYPE\s*(\d|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE)',
        r'ENNEAGRAM\s*(\d|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE)'
    ]
    detected_enneagram = []
    for pattern in enneagram_patterns:
        matches = re.findall(pattern, query_upper)
        detected_enneagram.extend(matches)
    
    return detected_mbti, detected_enneagram

def search_similar_blogs(conn, query_embedding, limit=10, type_filter=None):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        if type_filter:
            # First, filter to only blogs containing the type, THEN do semantic search on that subset
            cursor.execute('''
                WITH filtered_blogs AS (
                    SELECT 
                        url,
                        title,
                        text,
                        categories,
                        date,
                        embedding,
                        1 - (embedding <=> %s::vector) as similarity
                    FROM blogs_embeddings
                    WHERE embedding IS NOT NULL
                    AND (title ILIKE %s OR text ILIKE %s OR categories ILIKE %s)
                )
                SELECT 
                    url,
                    title,
                    text,
                    categories,
                    date,
                    similarity
                FROM filtered_blogs
                ORDER BY similarity DESC
                LIMIT %s
            ''', (query_embedding, f'%{type_filter}%', f'%{type_filter}%', f'%{type_filter}%', limit))
        else:
            # Regular search
            cursor.execute('''
                SELECT 
                    url,
                    title,
                    text,
                    categories,
                    date,
                    1 - (embedding <=> %s::vector) as similarity
                FROM blogs_embeddings
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            ''', (query_embedding, query_embedding, limit))
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

if 'conn' not in st.session_state:
    st.session_state.conn = create_connection()
if 'openai_client' not in st.session_state:
    st.session_state.openai_client = OpenAI(api_key=OPENAI_API_KEY)

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
        st.warning("No embeddings yet. Run generate_embeddings.py first!")
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

col1, col2 = st.columns([3, 1])
with col1:
    num_results = st.slider("Number of results", 1, 20, 10)
with col2:
    show_summaries = st.checkbox("Generate summaries", value=False)

if st.button("Search", type="primary") and search_query:
    stats = get_stats(st.session_state.conn)
    if stats['blogs_with_embeddings'] == 0:
        st.error("No embeddings available. Run generate_embeddings.py first.")
    else:
        with st.spinner("Searching..."):
            # Detect personality types in query
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
                st.success(f"Found {len(results)} most similar articles")
                
                for idx, result in enumerate(results, 1):
                    with st.expander(f"**{idx}. {result['title']}**", expanded=True):
                        col1, col2 = st.columns([2, 1])
                        with col1:
                            st.markdown(f"**Similarity Score:** {result['similarity']:.1%}")
                        with col2:
                            if result['date']:
                                st.markdown(f"**Date:** {result['date']}")
                        
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
            else:
                st.warning(f"No articles found matching '{type_filter}'. Try a different search.")

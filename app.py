# blog_search.py
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI
from secret_keys import *

st.set_page_config(page_title="Truity Blog Search", page_icon="🔍", layout="wide")

st.title("🔍 Debug: Index Investigation")

conn = psycopg2.connect(
    host=SUPABASE_HOST,
    port="5432",
    user="postgres.unspmmribsqbeuzhenmv",
    password=SUPABASE_PASSWORD,
    dbname="postgres",
    sslmode="require"
)
st.success("✅ Connected")

# Get OpenAI embedding
client = OpenAI(api_key=OPENAI_API_KEY)
response = client.embeddings.create(input="test query", model="text-embedding-3-small")
openai_embedding = response.data[0].embedding
embedding_str = '[' + ','.join(f'{x:.8f}' for x in openai_embedding) + ']'

test_limit = 10

# Check what indexes exist
st.header("Test 1: Check indexes on blogs_embeddings")
cursor = conn.cursor(cursor_factory=RealDictCursor)
cursor.execute("""
    SELECT indexname, indexdef 
    FROM pg_indexes 
    WHERE tablename = 'blogs_embeddings'
""")
indexes = cursor.fetchall()
for idx in indexes:
    st.write(f"**{idx['indexname']}**")
    st.code(idx['indexdef'])
cursor.close()

# Test: Disable index (use sequential scan)
st.header("Test 2: Force sequential scan (disable index)")
try:
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SET enable_indexscan = off")
    cursor.execute("SET enable_bitmapscan = off")
    cursor.execute("SET enable_indexonlyscan = off")
    
    query = f"""
        SELECT url, title, (embedding <=> '{embedding_str}'::vector) as distance
        FROM blogs_embeddings
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> '{embedding_str}'::vector
        LIMIT {test_limit}
    """
    
    cursor.execute(query)
    results = cursor.fetchall()
    st.success(f"✅ Sequential scan returned {len(results)} rows")
    
    for r in results:
        st.write(f"Distance {r['distance']:.4f}: {r['title'][:60]}")
    
    # Reset
    cursor.execute("SET enable_indexscan = on")
    cursor.execute("SET enable_bitmapscan = on")
    cursor.execute("SET enable_indexonlyscan = on")
    cursor.close()
except Exception as e:
    st.error(f"Failed: {e}")

# Test: EXPLAIN the query
st.header("Test 3: EXPLAIN ANALYZE")
try:
    cursor = conn.cursor()
    query = f"""
        EXPLAIN ANALYZE
        SELECT url, title
        FROM blogs_embeddings
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> '{embedding_str}'::vector
        LIMIT {test_limit}
    """
    cursor.execute(query)
    explain = cursor.fetchall()
    for row in explain:
        st.text(row[0])
    cursor.close()
except Exception as e:
    st.error(f"Failed: {e}")

conn.close()

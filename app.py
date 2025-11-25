# blog_search.py
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI
from secret_keys import *
import time

st.set_page_config(page_title="Truity Blog Search", page_icon="🔍", layout="wide")

st.title("🔍 Debug: Timeout Investigation")

# Connect
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

# Format with fewer decimals like DB does
embedding_str = '[' + ','.join(f'{x:.8f}' for x in openai_embedding) + ']'
st.write(f"Embedding string length: {len(embedding_str)}")

test_limit = 10

# Test 1: Check statement timeout setting
st.header("Test 1: Check timeout settings")
cursor = conn.cursor()
cursor.execute("SHOW statement_timeout")
st.write(f"statement_timeout: {cursor.fetchone()[0]}")
cursor.close()

# Test 2: Set no timeout and try
st.header("Test 2: Disable timeout")
try:
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SET statement_timeout = 0")
    cursor.execute("SET lock_timeout = 0")
    
    query = f"""
        SELECT url, title
        FROM blogs_embeddings
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> '{embedding_str}'::vector
        LIMIT {test_limit}
    """
    
    start = time.time()
    cursor.execute(query)
    exec_time = time.time() - start
    st.write(f"Query execution time: {exec_time:.3f}s")
    
    results = cursor.fetchall()
    st.write(f"Results: {len(results)} rows")
    cursor.close()
except Exception as e:
    st.error(f"Failed: {e}")

# Test 3: Use server-side cursor
st.header("Test 3: Server-side cursor")
try:
    cursor = conn.cursor('server_side_cursor', cursor_factory=RealDictCursor)
    
    query = f"""
        SELECT url, title
        FROM blogs_embeddings
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> '{embedding_str}'::vector
        LIMIT {test_limit}
    """
    
    cursor.execute(query)
    results = cursor.fetchall()
    st.write(f"Server-side cursor results: {len(results)} rows")
    cursor.close()
except Exception as e:
    st.error(f"Failed: {e}")

# Test 4: Direct connection (bypass pooler)
st.header("Test 4: Direct connection (port 5432 vs 6543)")
# Supabase pooler is usually on 6543, direct on 5432
# You're already on 5432, so let's try the transaction pooler
try:
    conn2 = psycopg2.connect(
        host=SUPABASE_HOST.replace("pooler", "db"),  # Try direct host
        port="5432",
        user="postgres.unspmmribsqbeuzhenmv",
        password=SUPABASE_PASSWORD,
        dbname="postgres",
        sslmode="require"
    )
    cursor = conn2.cursor(cursor_factory=RealDictCursor)
    
    query = f"""
        SELECT url, title
        FROM blogs_embeddings
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> '{embedding_str}'::vector
        LIMIT {test_limit}
    """
    
    cursor.execute(query)
    results = cursor.fetchall()
    st.write(f"Direct connection results: {len(results)} rows")
    cursor.close()
    conn2.close()
except Exception as e:
    st.write(f"Direct connection failed (expected if host doesn't exist): {e}")

# Test 5: Fetch one at a time
st.header("Test 5: Fetch rows one at a time")
try:
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    query = f"""
        SELECT url, title
        FROM blogs_embeddings
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> '{embedding_str}'::vector
        LIMIT {test_limit}
    """
    
    cursor.execute(query)
    
    rows = []
    for i in range(test_limit + 5):  # Try to fetch more than limit
        row = cursor.fetchone()
        if row is None:
            st.write(f"fetchone() returned None at iteration {i}")
            break
        rows.append(row)
        st.write(f"Row {i}: {row['title'][:50]}...")
    
    st.write(f"Total fetched: {len(rows)}")
    cursor.close()
except Exception as e:
    st.error(f"Failed: {e}")

conn.close()

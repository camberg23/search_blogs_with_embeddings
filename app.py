# blog_search.py
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI
from secret_keys import *

st.set_page_config(page_title="Truity Blog Search", page_icon="🔍", layout="wide")

st.title("🔍 Truity Blog Search - Debug Version")

# Step 1: Test database connection
st.header("Step 1: Database Connection")
try:
    conn = psycopg2.connect(
        host=SUPABASE_HOST,
        port="5432",
        user="postgres.unspmmribsqbeuzhenmv",
        password=SUPABASE_PASSWORD,
        dbname="postgres",
        sslmode="require"
    )
    st.success("✅ Database connected")
except Exception as e:
    st.error(f"❌ Database connection failed: {e}")
    st.stop()

# Step 2: Test simple count query
st.header("Step 2: Count Query")
try:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM blogs_embeddings WHERE embedding IS NOT NULL")
    count = cursor.fetchone()[0]
    cursor.close()
    st.success(f"✅ Count query worked: {count} rows with embeddings")
except Exception as e:
    st.error(f"❌ Count query failed: {e}")
    st.stop()

# Step 3: Test simple LIMIT query (no vector)
st.header("Step 3: Simple LIMIT Query (no vector)")
test_limit = 15
try:
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(f"SELECT url, title FROM blogs_embeddings WHERE embedding IS NOT NULL LIMIT {test_limit}")
    simple_results = cursor.fetchall()
    cursor.close()
    st.success(f"✅ Simple LIMIT query returned {len(simple_results)} rows (asked for {test_limit})")
except Exception as e:
    st.error(f"❌ Simple LIMIT query failed: {e}")
    st.stop()

# Step 4: Test vector query using existing embedding from DB
st.header("Step 4: Vector Query (using DB embedding)")
try:
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    query = f"""
        SELECT url, title, 1 - (embedding <=> (SELECT embedding FROM blogs_embeddings WHERE embedding IS NOT NULL LIMIT 1)) as similarity
        FROM blogs_embeddings
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> (SELECT embedding FROM blogs_embeddings WHERE embedding IS NOT NULL LIMIT 1)
        LIMIT {test_limit}
    """
    cursor.execute(query)
    vector_results = cursor.fetchall()
    cursor.close()
    st.success(f"✅ Vector query (DB embedding) returned {len(vector_results)} rows (asked for {test_limit})")
except Exception as e:
    st.error(f"❌ Vector query (DB embedding) failed: {e}")
    st.stop()

# Step 5: Test OpenAI embedding generation
st.header("Step 5: OpenAI Embedding")
try:
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.embeddings.create(
        input="test query",
        model="text-embedding-3-small"
    )
    test_embedding = response.data[0].embedding
    st.success(f"✅ OpenAI embedding generated: {len(test_embedding)} dimensions")
    st.write(f"First 5 values: {test_embedding[:5]}")
except Exception as e:
    st.error(f"❌ OpenAI embedding failed: {e}")
    st.stop()

# Step 6: Test vector query with OpenAI embedding as string
st.header("Step 6: Vector Query (OpenAI embedding as string)")
try:
    embedding_str = '[' + ','.join(str(x) for x in test_embedding) + ']'
    st.write(f"Embedding string length: {len(embedding_str)} chars")
    st.write(f"Embedding string starts with: {embedding_str[:100]}...")
    
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    query = f"""
        SELECT url, title, 1 - (embedding <=> '{embedding_str}'::vector) as similarity
        FROM blogs_embeddings
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> '{embedding_str}'::vector
        LIMIT {test_limit}
    """
    st.write(f"Query length: {len(query)} chars")
    
    cursor.execute(query)
    st.write("✅ Query executed")
    
    openai_vector_results = cursor.fetchall()
    st.write(f"✅ fetchall() returned {len(openai_vector_results)} rows")
    
    cursor.close()
    st.success(f"✅ Vector query (OpenAI embedding) returned {len(openai_vector_results)} rows (asked for {test_limit})")
    
    if len(openai_vector_results) < test_limit:
        st.error(f"🚨 BUG FOUND: Asked for {test_limit}, got {len(openai_vector_results)}")
except Exception as e:
    st.error(f"❌ Vector query (OpenAI embedding) failed: {e}")
    import traceback
    st.code(traceback.format_exc())
    st.stop()

# Step 7: Test with parameterized query
st.header("Step 7: Vector Query (parameterized)")
try:
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    query = """
        SELECT url, title, 1 - (embedding <=> %s::vector) as similarity
        FROM blogs_embeddings
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    cursor.execute(query, (embedding_str, embedding_str, test_limit))
    st.write("✅ Parameterized query executed")
    
    param_results = cursor.fetchall()
    st.write(f"✅ fetchall() returned {len(param_results)} rows")
    
    cursor.close()
    st.success(f"✅ Parameterized query returned {len(param_results)} rows (asked for {test_limit})")
    
    if len(param_results) < test_limit:
        st.error(f"🚨 BUG FOUND: Asked for {test_limit}, got {len(param_results)}")
except Exception as e:
    st.error(f"❌ Parameterized query failed: {e}")
    import traceback
    st.code(traceback.format_exc())

# Step 8: Check rowcount
st.header("Step 8: Check cursor.rowcount")
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
    st.write(f"cursor.rowcount after execute: {cursor.rowcount}")
    
    results = cursor.fetchall()
    st.write(f"len(fetchall()): {len(results)}")
    
    cursor.close()
except Exception as e:
    st.error(f"❌ Rowcount check failed: {e}")

# Cleanup
conn.close()
st.header("Done")
st.write("Check above for 🚨 to find where the bug is.")

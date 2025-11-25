# blog_search.py
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI
from secret_keys import *

st.set_page_config(page_title="Truity Blog Search", page_icon="🔍", layout="wide")

st.title("🔍 Debug: Embedding Format Investigation")

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
st.write(f"OpenAI embedding type: {type(openai_embedding)}")
st.write(f"OpenAI embedding[0] type: {type(openai_embedding[0])}")

# Get a DB embedding for comparison
cursor = conn.cursor()
cursor.execute("SELECT embedding::text FROM blogs_embeddings WHERE embedding IS NOT NULL LIMIT 1")
db_embedding_str = cursor.fetchone()[0]
cursor.close()
st.write(f"DB embedding string length: {len(db_embedding_str)}")
st.write(f"DB embedding starts with: {db_embedding_str[:100]}")

# Test different string formats
st.header("Testing Different String Formats")

test_limit = 10

# Format 1: Current approach
format1 = '[' + ','.join(str(x) for x in openai_embedding) + ']'
st.write(f"Format 1 (str): {format1[:80]}...")

# Format 2: repr
format2 = '[' + ','.join(repr(x) for x in openai_embedding) + ']'
st.write(f"Format 2 (repr): {format2[:80]}...")

# Format 3: Fixed precision
format3 = '[' + ','.join(f'{x:.10f}' for x in openai_embedding) + ']'
st.write(f"Format 3 (fixed 10): {format3[:80]}...")

# Format 4: Scientific notation avoided
format4 = '[' + ','.join(f'{x:.15g}' for x in openai_embedding) + ']'
st.write(f"Format 4 (15g): {format4[:80]}...")

# Test each format
formats = [
    ("str(x)", format1),
    ("repr(x)", format2),
    (".10f", format3),
    (".15g", format4),
]

for name, emb_str in formats:
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        query = f"""
            SELECT url, title
            FROM blogs_embeddings
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> '{emb_str}'::vector
            LIMIT {test_limit}
        """
        cursor.execute(query)
        results = cursor.fetchall()
        cursor.close()
        
        if len(results) == test_limit:
            st.success(f"✅ Format '{name}': {len(results)} rows")
        else:
            st.error(f"❌ Format '{name}': {len(results)} rows (expected {test_limit})")
    except Exception as e:
        st.error(f"❌ Format '{name}' failed: {e}")

# Also test: what if we insert the OpenAI embedding and read it back?
st.header("Test: Round-trip through DB")
try:
    cursor = conn.cursor()
    # Insert into a temp check
    cursor.execute(f"SELECT '{format1}'::vector")
    result = cursor.fetchone()
    st.write(f"Cast result type: {type(result[0])}")
    st.write(f"Cast result: {str(result[0])[:100]}...")
    cursor.close()
except Exception as e:
    st.error(f"Cast test failed: {e}")

conn.close()

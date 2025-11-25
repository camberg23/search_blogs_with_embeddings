# blog_search.py
import streamlit as st
import psycopg2
from psycopg2.extras import RealDictCursor
from openai import OpenAI
from secret_keys import *

st.set_page_config(page_title="Truity Blog Search", page_icon="🔍", layout="wide")

st.title("🔍 Debug: Vector Dimension Check")

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

st.write(f"OpenAI embedding length: {len(openai_embedding)}")

# Format it
embedding_str = '[' + ','.join(f'{x:.8f}' for x in openai_embedding) + ']'

# Check what dimension PostgreSQL thinks our vector is
st.header("Test: What dimension does PostgreSQL see?")
cursor = conn.cursor()
cursor.execute(f"SELECT vector_dims('{embedding_str}'::vector)")
parsed_dims = cursor.fetchone()[0]
st.write(f"PostgreSQL parsed dimension: {parsed_dims}")
cursor.close()

# Check what dimension the DB embeddings are
st.header("Test: DB embedding dimensions")
cursor = conn.cursor()
cursor.execute("SELECT vector_dims(embedding) FROM blogs_embeddings WHERE embedding IS NOT NULL LIMIT 1")
db_dims = cursor.fetchone()[0]
st.write(f"DB embedding dimension: {db_dims}")
cursor.close()

# Are they the same?
if parsed_dims == db_dims:
    st.success(f"✅ Dimensions match: {parsed_dims}")
else:
    st.error(f"❌ DIMENSION MISMATCH: OpenAI={parsed_dims}, DB={db_dims}")

# Test: What if we check for NaN or Inf in OpenAI embedding?
st.header("Test: Check for NaN/Inf in embedding")
import math
has_nan = any(math.isnan(x) for x in openai_embedding)
has_inf = any(math.isinf(x) for x in openai_embedding)
st.write(f"Has NaN: {has_nan}")
st.write(f"Has Inf: {has_inf}")

# Test: Check min/max values
st.write(f"Min value: {min(openai_embedding)}")
st.write(f"Max value: {max(openai_embedding)}")

# Test: Count how many rows have distance < infinity from our vector
st.header("Test: Count rows with finite distance")
cursor = conn.cursor()
query = f"""
    SELECT COUNT(*) 
    FROM blogs_embeddings 
    WHERE embedding IS NOT NULL 
    AND (embedding <=> '{embedding_str}'::vector) < 'infinity'::float
"""
cursor.execute(query)
finite_count = cursor.fetchone()[0]
st.write(f"Rows with finite distance: {finite_count}")
cursor.close()

# Test: Count rows with distance < 2 (max cosine distance)
st.header("Test: Count rows with distance < 2")
cursor = conn.cursor()
query = f"""
    SELECT COUNT(*) 
    FROM blogs_embeddings 
    WHERE embedding IS NOT NULL 
    AND (embedding <=> '{embedding_str}'::vector) < 2
"""
cursor.execute(query)
close_count = cursor.fetchone()[0]
st.write(f"Rows with distance < 2: {close_count}")
cursor.close()

# Test: What's the actual distance to the top result?
st.header("Test: Distance to results")
cursor = conn.cursor(cursor_factory=RealDictCursor)
query = f"""
    SELECT title, (embedding <=> '{embedding_str}'::vector) as distance
    FROM blogs_embeddings 
    WHERE embedding IS NOT NULL
    ORDER BY embedding <=> '{embedding_str}'::vector
    LIMIT 5
"""
cursor.execute(query)
results = cursor.fetchall()
for r in results:
    st.write(f"Distance {r['distance']}: {r['title'][:50]}")
cursor.close()

conn.close()

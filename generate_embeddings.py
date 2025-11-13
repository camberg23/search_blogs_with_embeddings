# generate_embeddings.py
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
from openai import OpenAI
import time
from datetime import datetime
from secret_keys import *

load_dotenv()

def create_connection():
    """Create a connection to Supabase."""
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
    """Get embedding for a text string using OpenAI."""
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
    with conn.cursor() as cursor:
        cursor.execute('''
            INSERT INTO blogs_embeddings (url, rss_content, categories, title, text, date, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
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
            embedding
        ))
    conn.commit()

def main():
    print("=" * 60)
    print("BATCH EMBEDDINGS GENERATION")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    conn = create_connection()
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    blogs_needing_embeddings = get_blogs_needing_embeddings(conn)
    
    if not blogs_needing_embeddings:
        print("✅ All blogs already have embeddings!")
        conn.close()
        return
    
    print(f"Found {len(blogs_needing_embeddings)} blogs needing embeddings\n")
    
    successful = 0
    failed = 0
    
    for idx, blog in enumerate(blogs_needing_embeddings, 1):
        try:
            text_to_embed = f"{blog['title']}\n\n{blog['text']}"
            
            max_chars = 8000
            if len(text_to_embed) > max_chars:
                text_to_embed = text_to_embed[:max_chars]
            
            print(f"[{idx}/{len(blogs_needing_embeddings)}] Processing: {blog['title'][:60]}...")
            
            embedding = get_embedding(text_to_embed, client)
            insert_blog_with_embedding(conn, blog, embedding)
            
            successful += 1
            print(f"  ✅ Success")
            
            if idx < len(blogs_needing_embeddings):
                time.sleep(0.2)
                
        except Exception as e:
            failed += 1
            print(f"  ❌ Failed: {e}")
            continue
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Total: {len(blogs_needing_embeddings)}")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    conn.close()

if __name__ == "__main__":
    main()
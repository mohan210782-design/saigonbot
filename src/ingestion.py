"""
Ingestion Pipeline: Load menu data and index into ChromaDB with embeddings
"""
import json
import chromadb
from pathlib import Path
from typing import List, Dict
import ollama
from tqdm import tqdm


def load_menu_items(json_path: str) -> List[Dict]:
    """Load menu items from JSON"""
    with open(json_path, 'r', encoding='utf-8') as f:
        items = json.load(f)
    print(f"📦 Loaded {len(items)} menu items from {json_path}")
    return items


def create_text_chunk(item: Dict) -> str:
    """Create searchable text chunk from menu item"""
    parts = []
    
    # Item name (most important)
    parts.append(item['item_name'])
    
    # Section
    if item.get('section') and item['section'] != 'UNKNOWN':
        parts.append(f"Section: {item['section']}")
    
    # Price
    if item.get('price'):
        parts.append(f"Price: {item['price']:,.0f} {item.get('currency', 'VND')}")
    
    # Tags
    if item.get('tags') and item['tags'] != ['unknown']:
        tags_str = ', '.join(item['tags'])
        parts.append(f"Tags: {tags_str}")
    
    return '. '.join(parts)


def get_embedding(text: str, model: str = "mxbai-embed-large") -> List[float]:
    """Get embedding from Ollama"""
    try:
        response = ollama.embeddings(model=model, prompt=text)
        return response['embedding']
    except Exception as e:
        print(f"⚠️  Error getting embedding: {e}")
        raise


def setup_chromadb(persist_directory: str = "chroma_db"):
    """Setup ChromaDB collection"""
    client = chromadb.PersistentClient(path=persist_directory)
    
    # Create or get collection
    collection_name = "hotel_saigon_menu"
    try:
        collection = client.get_collection(name=collection_name)
        print(f"📂 Using existing collection: {collection_name}")
        print(f"   Current items: {collection.count()}")
    except:
        collection = client.create_collection(
            name=collection_name,
            metadata={"description": "Hotel Saigon menu items with embeddings"}
        )
        print(f"✅ Created new collection: {collection_name}")
    
    return collection


def batch_embeddings(texts: List[str], model: str = "mxbai-embed-large", batch_size: int = 10):
    """Generate embeddings in batches"""
    embeddings = []
    
    print(f"🔄 Generating embeddings using {model}...")
    for i in tqdm(range(0, len(texts), batch_size), desc="Embedding batches"):
        batch = texts[i:i + batch_size]
        batch_embeds = []
        
        for text in batch:
            try:
                embedding = get_embedding(text, model)
                batch_embeds.append(embedding)
            except Exception as e:
                print(f"⚠️  Error embedding text: {text[:50]}... - {e}")
                # Use zero vector as fallback
                batch_embeds.append([0.0] * 1024)  # mxbai-embed-large is 1024 dim
        
        embeddings.extend(batch_embeds)
    
    return embeddings


def index_menu_items(collection, items: List[Dict], model: str = "mxbai-embed-large"):
    """Index menu items into ChromaDB"""
    print(f"\n📝 Indexing {len(items)} menu items...")
    
    # Prepare data
    ids = []
    texts = []
    metadatas = []
    
    for item in items:
        # Create ID
        item_id = item['id']
        ids.append(item_id)
        
        # Create text chunk for embedding
        text_chunk = create_text_chunk(item)
        texts.append(text_chunk)
        
        # Prepare metadata (ChromaDB requires string values)
        metadata = {
            'item_number': str(item['item_number']),
            'item_name': item['item_name'],
            'section': item.get('section', 'UNKNOWN'),
            'price': str(item.get('price', '')) if item.get('price') else '',
            'currency': item.get('currency', '') or '',
            'tags': ', '.join(item.get('tags', [])),
            'source': item.get('source', 'saigon.pdf')
        }
        metadatas.append(metadata)
    
    # Generate embeddings
    embeddings = batch_embeddings(texts, model)
    
    # Add to ChromaDB
    print(f"\n💾 Storing items in ChromaDB...")
    try:
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas
        )
        print(f"✅ Successfully indexed {len(items)} items")
    except Exception as e:
        print(f"❌ Error indexing: {e}")
        # Try updating existing items
        try:
            collection.update(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas
            )
            print(f"✅ Updated {len(items)} items")
        except Exception as e2:
            print(f"❌ Update also failed: {e2}")
            raise


def validate_indexing(collection, test_queries: List[str] = None):
    """Validate indexing with test queries"""
    if test_queries is None:
        test_queries = [
            "vegetarian dosa",
            "chicken curry",
            "beverages under 50000",
            "breakfast items",
            "mutton dishes"
        ]
    
    print(f"\n🔍 Validating indexing with test queries...")
    
    for query in test_queries:
        print(f"\n   Query: '{query}'")
        
        # Get embedding for query
        try:
            query_embedding = get_embedding(query)
            
            # Search
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=3
            )
            
            if results['ids'] and len(results['ids'][0]) > 0:
                print(f"   Top results:")
                for i, (item_id, distance) in enumerate(zip(results['ids'][0], results['distances'][0])):
                    metadata = results['metadatas'][0][i]
                    print(f"     {i+1}. {metadata['item_name']} ({metadata['section']}) - Distance: {distance:.4f}")
            else:
                print(f"   ⚠️  No results found")
        except Exception as e:
            print(f"   ❌ Error: {e}")


def main():
    """Main ingestion function"""
    project_root = Path(__file__).parent.parent
    menu_json = project_root / "data" / "processed" / "menu_items.json"
    chroma_dir = project_root / "chroma_db"
    
    # Load menu items
    items = load_menu_items(str(menu_json))
    
    # Setup ChromaDB
    collection = setup_chromadb(str(chroma_dir))
    
    # Check if already indexed
    if collection.count() > 0:
        print(f"\n⚠️  Collection already has {collection.count()} items")
        response = input("   Re-index? This will replace existing data (y/n): ").strip().lower()
        if response == 'y':
            # Delete and recreate
            collection.delete()
            client = chromadb.PersistentClient(path=str(chroma_dir))
            collection = client.create_collection(
                name="hotel_saigon_menu",
                metadata={"description": "Hotel Saigon menu items with embeddings"}
            )
            print("   ✅ Cleared existing collection")
        else:
            print("   ℹ️  Skipping indexing")
            validate_indexing(collection)
            return
    
    # Index items
    index_menu_items(collection, items, model="mxbai-embed-large")
    
    # Validate
    validate_indexing(collection)
    
    print(f"\n✅ Ingestion complete!")
    print(f"   Collection: hotel_saigon_menu")
    print(f"   Items indexed: {collection.count()}")
    print(f"   Storage: {chroma_dir}")


if __name__ == "__main__":
    main()

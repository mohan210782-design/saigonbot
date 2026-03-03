#!/usr/bin/env python3
"""
Fine-tuning analysis script
Tests intent detection and retrieval coverage for sample queries
"""
import sys
import json
from pathlib import Path
from typing import List, Dict, Tuple

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from intent_classifier import get_intent_classifier, IntentCategory, IntentType
from rag import RAGPipeline


def parse_queries(file_path: Path) -> List[Dict]:
    """Parse queries from sample_queries.txt"""
    queries = []
    current_category = None
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Split by lines
    lines = content.split('\n')
    
    for line in lines:
        original_line = line
        line = line.strip()
        if not line:
            continue
        
        # Category headers (emoji + text)
        if any(line.startswith(emoji) for emoji in ['🍛', '🌶', '🥦', '👨', '🍽', '🏨', '💬']):
            current_category = line
            continue
        
        # Query lines (bullet points with quotes) - handle various bullet characters
        bullet_chars = ['•', '·', '-', '*']
        is_bullet = any(line.startswith(char) for char in bullet_chars)
        
        if is_bullet:
            # Extract query from bullet point
            for bullet in bullet_chars:
                if line.startswith(bullet):
                    query = line[len(bullet):].strip()
                    break
            else:
                query = line[1:].strip()
            
            # Remove quotes if present (handle both regular and curly quotes)
            # Remove from start
            while query and query[0] in ['"', '"', '"', "'", "'"]:
                query = query[1:]
            # Remove from end
            while query and query[-1] in ['"', '"', '"', "'", "'"]:
                query = query[:-1]
            
            if query:  # Only add non-empty queries
                queries.append({
                    'query': query,
                    'category': current_category or 'Unknown'
                })
    
    return queries


def test_intent_detection(queries: List[Dict]) -> Dict:
    """Test intent classification for all queries"""
    classifier = get_intent_classifier()
    
    results = {
        'total': len(queries),
        'by_category': {},
        'by_intent': {},
        'misclassified': [],
        'low_confidence': []
    }
    
    print("=" * 80)
    print("INTENT DETECTION ANALYSIS")
    print("=" * 80)
    
    for i, item in enumerate(queries, 1):
        query = item['query']
        category = item['category']
        
        intent_result = classifier.classify_intent(query)
        intent_type = intent_result.intent_type
        intent_category = intent_result.category
        confidence = intent_result.confidence
        
        # Track by category
        if category not in results['by_category']:
            results['by_category'][category] = []
        results['by_category'][category].append({
            'query': query,
            'intent': intent_type.value,
            'category': intent_category.value,
            'confidence': confidence
        })
        
        # Track by intent
        intent_key = intent_type.value
        if intent_key not in results['by_intent']:
            results['by_intent'][intent_key] = []
        results['by_intent'][intent_key].append(query)
        
        # Flag potential issues
        if confidence < 0.5:
            results['low_confidence'].append({
                'query': query,
                'intent': intent_type.value,
                'confidence': confidence
            })
        
        # Check for misclassification (heuristic based on category)
        expected_category = None
        if 'Casual' in category or 'Spicy' in category or 'Vegetarian' in category or \
           'Family' in category or 'Order-Like' in category or 'Emotional' in category:
            expected_category = IntentCategory.MENU
        elif 'Restaurant Information' in category:
            expected_category = IntentCategory.RESTAURANT_INFO
        
        if expected_category and intent_category != expected_category:
            results['misclassified'].append({
                'query': query,
                'expected': expected_category.value,
                'got': intent_category.value,
                'confidence': confidence
            })
    
    return results


def test_retrieval_coverage(queries: List[Dict], pipeline: RAGPipeline) -> Dict:
    """Test retrieval coverage for menu queries"""
    print("\n" + "=" * 80)
    print("RETRIEVAL COVERAGE ANALYSIS")
    print("=" * 80)
    
    menu_queries = []
    for item in queries:
        category = item['category']
        if 'Casual' in category or 'Spicy' in category or 'Vegetarian' in category or \
           'Family' in category or 'Order-Like' in category or 'Emotional' in category:
            menu_queries.append(item['query'])
    
    results = {
        'total_menu_queries': len(menu_queries),
        'zero_results': [],
        'low_results': [],  # < 3 items
        'good_results': [],  # >= 3 items
        'coverage_stats': {}
    }
    
    for query in menu_queries:
        try:
            retrieved = pipeline.retrieve(query, top_k=7, doc_type='menu')
            count = len(retrieved)
            
            if count == 0:
                results['zero_results'].append(query)
            elif count < 3:
                results['low_results'].append({
                    'query': query,
                    'count': count
                })
            else:
                results['good_results'].append({
                    'query': query,
                    'count': count
                })
            
            # Store coverage stats
            results['coverage_stats'][query] = {
                'retrieved': count,
                'items': [item.get('metadata', {}).get('item_name', 'Unknown') for item in retrieved[:3]]
            }
            
        except Exception as e:
            print(f"⚠️  Error retrieving for '{query}': {e}")
            results['zero_results'].append(query)
    
    return results


def print_analysis(intent_results: Dict, retrieval_results: Dict):
    """Print analysis summary"""
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    # Intent detection summary
    print(f"\n📋 INTENT DETECTION:")
    print(f"   Total queries: {intent_results['total']}")
    print(f"   Intent types found: {len(intent_results['by_intent'])}")
    print(f"   Low confidence (<0.5): {len(intent_results['low_confidence'])}")
    print(f"   Potential misclassifications: {len(intent_results['misclassified'])}")
    
    if intent_results['misclassified']:
        print(f"\n   ⚠️  MISCLASSIFIED QUERIES:")
        for item in intent_results['misclassified']:
            print(f"      '{item['query']}'")
            print(f"         Expected: {item['expected']}, Got: {item['got']} (conf: {item['confidence']:.2f})")
    
    if intent_results['low_confidence']:
        print(f"\n   ⚠️  LOW CONFIDENCE QUERIES:")
        for item in intent_results['low_confidence'][:10]:  # Show first 10
            print(f"      '{item['query']}' -> {item['intent']} (conf: {item['confidence']:.2f})")
    
    # Retrieval coverage summary
    print(f"\n🔍 RETRIEVAL COVERAGE:")
    print(f"   Total menu queries tested: {retrieval_results['total_menu_queries']}")
    print(f"   Zero results: {len(retrieval_results['zero_results'])}")
    print(f"   Low results (<3 items): {len(retrieval_results['low_results'])}")
    print(f"   Good results (>=3 items): {len(retrieval_results['good_results'])}")
    
    if retrieval_results['zero_results']:
        print(f"\n   ⚠️  ZERO RESULTS QUERIES:")
        for query in retrieval_results['zero_results']:
            print(f"      '{query}'")
    
    if retrieval_results['low_results']:
        print(f"\n   ⚠️  LOW RESULTS QUERIES (<3 items):")
        for item in retrieval_results['low_results'][:10]:  # Show first 10
            print(f"      '{item['query']}' -> {item['count']} items")
    
    # Intent distribution
    print(f"\n📊 INTENT DISTRIBUTION:")
    for intent, queries in sorted(intent_results['by_intent'].items(), key=lambda x: len(x[1]), reverse=True):
        print(f"   {intent}: {len(queries)} queries")
        if len(queries) <= 5:
            print(f"      Examples: {', '.join(queries[:3])}")


def generate_recommendations(intent_results: Dict, retrieval_results: Dict) -> List[str]:
    """Generate recommendations for improvements"""
    recommendations = []
    
    # Intent detection recommendations
    if intent_results['misclassified']:
        recommendations.append(
            "INTENT: Add patterns for misclassified queries in intent_classifier.py"
        )
    
    if intent_results['low_confidence']:
        recommendations.append(
            "INTENT: Review low-confidence queries and add more specific patterns"
        )
    
    # Retrieval recommendations
    if retrieval_results['zero_results']:
        recommendations.append(
            "RETRIEVAL: Zero-result queries may need better embeddings or query expansion"
        )
        recommendations.append(
            "RETRIEVAL: Consider adding synonyms/keywords to menu item descriptions"
        )
    
    if retrieval_results['low_results']:
        recommendations.append(
            "RETRIEVAL: Low-result queries may benefit from increasing TOP_K or improving query understanding"
        )
    
    # Template recommendations
    menu_count = sum(len(queries) for intent, queries in intent_results['by_intent'].items() 
                     if 'MENU' in intent or 'FOOD' in intent)
    if menu_count > 0:
        recommendations.append(
            "TEMPLATES: Create specialized templates for mood-based queries (comforting, spicy, etc.)"
        )
        recommendations.append(
            "TEMPLATES: Add templates for family/group queries with portion suggestions"
        )
    
    return recommendations


def main():
    """Main analysis function"""
    print("🔍 Fine-tuning Analysis Tool")
    print("=" * 80)
    
    # Parse queries
    queries_file = Path(__file__).parent / "data" / "sample_queries.txt"
    queries = parse_queries(queries_file)
    
    print(f"\n✅ Loaded {len(queries)} queries from {queries_file}")
    
    # Test intent detection
    intent_results = test_intent_detection(queries)
    
    # Initialize RAG pipeline for retrieval testing
    print("\n🔄 Initializing RAG pipeline...")
    project_root = Path(__file__).parent
    chroma_db_path = project_root / "chroma_db"
    pipeline = RAGPipeline(chroma_db_path=str(chroma_db_path), use_reranking=False)
    
    # Test retrieval coverage
    retrieval_results = test_retrieval_coverage(queries, pipeline)
    
    # Print analysis
    print_analysis(intent_results, retrieval_results)
    
    # Generate recommendations
    recommendations = generate_recommendations(intent_results, retrieval_results)
    
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    for i, rec in enumerate(recommendations, 1):
        print(f"{i}. {rec}")
    
    # Save detailed results to JSON
    output_file = Path(__file__).parent / "data" / "fine_tuning_analysis.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'intent_results': {
                'by_intent': intent_results['by_intent'],
                'misclassified': intent_results['misclassified'],
                'low_confidence': intent_results['low_confidence']
            },
            'retrieval_results': {
                'zero_results': retrieval_results['zero_results'],
                'low_results': retrieval_results['low_results'],
                'coverage_stats': retrieval_results['coverage_stats']
            },
            'recommendations': recommendations
        }, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Detailed results saved to: {output_file}")
    print("\n📝 Next steps:")
    print("   1. Review the analysis above")
    print("   2. Provide current bot responses for queries you want improved")
    print("   3. I'll update templates/prompts based on your feedback")


if __name__ == "__main__":
    main()

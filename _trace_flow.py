"""Trace flow for 'Who is your partner?'"""
import os, sys, re, json
os.environ['BOT_IDENTITY'] = 'robotics'
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, 'd:/chikku/chikku-robotics-dev/src')
from intent_classifier import get_intent_classifier
from knowledge_base import get_knowledge_base

ic = get_intent_classifier()
kb = get_knowledge_base()
q = 'Who is your partner?'

# 1. INTENT
r = ic.classify_intent(q)
print('=== 1. INTENT CLASSIFICATION ===')
print(f'    Type: {r.intent_type.value}')
print(f'    Category: {r.category.value}')
print(f'    Confidence: {r.confidence}')
print(f'    Requires clarification: {r.requires_clarification}')
print(f'    → Routes to: {"IDENTITY/CONVERSATIONAL handler" if r.category.value in ["identity","conversational"] else "FAQ search (CLARIFICATION_NEEDED path)"}')

# 2. FAQ MATCH
print()
print('=== 2. FAQ SEARCH (get_best_faq_match) ===')
faq_answer = kb.get_best_faq_match(q)
if faq_answer:
    print(f'    ✅ MATCHED: {faq_answer[:200]}...')
else:
    print(f'    ❌ NO MATCH in FAQ')

# 3. Keyword analysis
print()
print('=== 3. KEYWORD ANALYSIS ===')
ql = q.lower().strip()
qc = re.sub(r'[?.,!;:()\[\]{}"\']', '', ql)
stop_words = {'the','and','for','are','you','your','what','how','does','can','will','with','that','this','from','have','has','been','who','is'}
qw = [w for w in qc.split() if len(w) > 2 and w not in stop_words]
print(f'    Query words (meaningful): {qw}')
print(f'    Min score needed: {max(2, len(qw) * 0.3):.1f}')

faq_items = kb.get_faq()
print(f'    Total FAQ items: {len(faq_items)}')
print(f'    FAQ items with matching words:')
for item in faq_items:
    qn = item.get('question', '').lower()
    qn_clean = re.sub(r'[?.,!;:()\[\]{}"\']', '', qn)
    score = sum(1 for w in qw if w in qn_clean)
    if score > 0:
        print(f'      Score {score}: "{item.get("question", "")}"')

# 4. Check partnerships.json
print()
print('=== 4. PARTNERSHIPS DATA ===')
import pathlib
pp = pathlib.Path('d:/chikku/chikku-robotics-dev/data/knowledge_base/robotics/partnerships.json')
if pp.exists():
    with open(pp) as f:
        data = json.load(f)
    print(f'    Keys: {list(data.keys())}')
    # Show first few entries
    for k, v in data.items():
        if isinstance(v, dict):
            print(f'    {k}: {json.dumps(v, indent=6)[:200]}')
else:
    print('    File not found!')

# 5. What happens next in rag.py query()
print()
print('=== 5. FULL FLOW ===')
print("""
    query("Who is your partner?")
        │
        ├─ Step 1: _classify_intent() → CLARIFICATION_NEEDED (confidence 0.3)
        │
        ├─ Step 2: Not IDENTITY or CONVERSATIONAL → skip
        │
        ├─ Step 3: _try_faq_answer() → get_best_faq_match()
        │           └─ Query words: ['partner']
        │           └─ Matching FAQ items with 'partner': ...
        │           └─ If score >= 2 or >= 30%: RETURN FAQ answer
        │           └─ Otherwise: NO MATCH → continue
        │
        ├─ Step 4: ChromaDB retrieve("Who is your partner?")
        │           └─ Vector search in chikku_robotics collection
        │           └─ Returns relevant chunks if partnerships.json was indexed
        │
        └─ Step 5: Fallback LLM with company info
                    └─ Uses system_prompt_robotics.txt + about_robotics.txt
""")

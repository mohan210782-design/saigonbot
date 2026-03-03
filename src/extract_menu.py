"""
Complete menu extraction from saigon.pdf - handles all cases
"""
import re
import json
from pathlib import Path
import pdfplumber
from typing import List, Dict, Optional, Tuple


def extract_all_text(pdf_path: str) -> str:
    """Extract all text from PDF"""
    texts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                texts.append(text)
    return '\n'.join(texts)


def normalize_text(text: str) -> str:
    """Normalize text - fix common issues"""
    # Fix word breaks
    text = re.sub(r'\bLEMOMN\b', 'LEMON', text, flags=re.IGNORECASE)
    # Normalize whitespace but keep newlines
    text = re.sub(r'[ \t]+', ' ', text)
    return text


def find_sections(text: str) -> List[Tuple[int, str]]:
    """Find all section headers and their positions"""
    sections = []
    # Section patterns - specific known sections only
    section_patterns = [
        (r'^NATIVE\s+(?:HOT|COLD)\s+BEVERAGES', 'NATIVE HOT BEVERAGES'),
        (r'^NATIVE\s+COLD\s+BEVERAGES', 'NATIVE COLD BEVERAGES'),
        (r'^HOT\s+&\s+COLD\s+BEVERAGES', 'HOT & COLD BEVERAGES'),
        (r'^COCKTAILS$', 'COCKTAILS'),
        (r'^MOCKTAILS$', 'MOCKTAILS'),
        (r'^BEER$', 'BEER'),
        (r'^WINE$', 'WINE'),
        (r'^LIQUOR$', 'LIQUOR'),
        (r'^BREAKFAST$', 'BREAKFAST'),
        (r'^SOUTH\s+INDIAN\s+CUISINE', 'SOUTH INDIAN CUISINE'),
        (r'^SOUPS$', 'SOUPS'),
        (r'^APPETIZERS$', 'APPETIZERS'),
        (r'^DOSA\s+CORNER', 'DOSA CORNER'),
        (r'^STARTERS\s+FROM\s+THE\s+SOUTH', 'STARTERS FROM THE SOUTH'),
        (r'^BREAD\s+CORNER', 'BREAD CORNER'),
        (r'^MAIN\s+COURSE\s+VEG\s+&', 'MAIN COURSE VEG & NON-VEG'),
        (r'^MAIN\s+COURSE\s+VEG$', 'MAIN COURSE VEG'),
        (r'^CURRY$', 'CURRY'),
        (r'^CHILLY$', 'CHILLY'),
        (r'^HARIYALI$', 'HARIYALI'),
        (r'^KOFTA$', 'KOFTA'),
        (r'^MUTTON$', 'MUTTON'),
        (r'^RAITA$', 'RAITA'),
        (r'^VEGETABLE$', 'VEGETABLE'),
    ]
    
    lines = text.split('\n')
    for i, line in enumerate(lines):
        line_clean = line.strip().upper()
        if not line_clean or re.match(r'^\d+\.', line_clean):
            continue
        
        # Check if line matches any section pattern exactly
        for pattern, section_name in section_patterns:
            if re.match(pattern, line_clean, re.IGNORECASE):
                sections.append((i, section_name))
                break
    
    return sections


def extract_item_number(line: str) -> Optional[int]:
    """Extract item number from line"""
    match = re.match(r'^(\d+)\.', line.strip())
    if match:
        try:
            return int(match.group(1))
        except:
            return None
    return None


def parse_price_from_text(text: str) -> Optional[float]:
    """Extract price from text"""
    match = re.search(r'VND\s*([\d,]+)', text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(',', ''))
        except:
            return None
    return None


def extract_item_name(text: str) -> str:
    """Extract clean item name from text"""
    # Remove item number
    text = re.sub(r'^\d+\.\s*', '', text)
    # Remove price
    text = re.sub(r'\s*VND\s*[\d,]+.*$', '', text, flags=re.IGNORECASE)
    # Remove time info in parentheses at start
    text = re.sub(r'^\s*\([^)]*\)\s*', '', text)
    # Remove descriptions (long text after item name)
    # Look for description keywords
    desc_keywords = [
        r'\b(served|garnished|topped|filled|stuffed|dipped|fried|steamed|marinated|tossed|prepared|made|immersed|sautéed)',
        r'\b(crispy|spicy|mild|thick|thin|boneless|tender|fresh|special)',
        r'\b(crepe|pancake|doughnut|dumpling|patty|soup|curry)',
    ]
    
    for keyword in desc_keywords:
        match = re.search(keyword, text, re.IGNORECASE)
        if match and match.start() > 0:
            # Check if it's likely a description (has more words after keyword)
            remaining = text[match.start():]
            if len(remaining.split()) > 5:
                text = text[:match.start()].strip()
                break
    
    # If still too long, take first reasonable portion
    words = text.split()
    if len(words) > 10:
        text = ' '.join(words[:8])
    
    # Final cleanup
    text = re.sub(r'\s*\([^)]*\)\s*', '', text)  # Remove any remaining parentheses
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def parse_all_items(text: str) -> List[Dict]:
    """Parse all menu items from text"""
    items = []
    lines = text.split('\n')
    
    # Find sections
    sections = find_sections(text)
    section_map = {}
    for line_idx, section_name in sections:
        section_map[line_idx] = section_name
    
    # Track current section
    current_section = None
    seen_numbers = set()
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Update current section
        if i in section_map:
            current_section = section_map[i]
            i += 1
            continue
        
        # Skip empty lines, time info, descriptions
        if (not line or 
            re.match(r'^\([^)]*\)$', line) or
            (line.isupper() and len(line.split()) >= 2 and i not in section_map and not re.match(r'^\d+\.', line))):
            i += 1
            continue
        
        # Check for item number
        item_num = extract_item_number(line)
        if item_num and item_num not in seen_numbers:
            seen_numbers.add(item_num)
            
            # Collect item text (current line + next few lines if needed)
            item_text = line
            price = parse_price_from_text(line)
            
            # If no price on this line, check next 3 lines
            if not price:
                for j in range(i+1, min(i+4, len(lines))):
                    next_line = lines[j].strip()
                    if not next_line:
                        continue
                    
                    # Stop if we hit another item or section
                    if (extract_item_number(next_line) or 
                        j in section_map or
                        (next_line.isupper() and len(next_line.split()) >= 2)):
                        break
                    
                    # Check for price
                    price_found = parse_price_from_text(next_line)
                    if price_found:
                        price = price_found
                        # Don't include price line in item name
                        break
                    else:
                        # Might be continuation of item name (if short and not all caps)
                        if (len(next_line.split()) <= 6 and 
                            not next_line.isupper() and
                            not re.match(r'^[A-Z\s&/]+$', next_line)):
                            item_text += ' ' + next_line
            
            # Extract item name
            item_name = extract_item_name(item_text)
            
            # Validate item name
            if (item_name and 
                len(item_name) > 1 and 
                not item_name.replace('.', '').isdigit() and
                len(item_name.split()) < 30):
                
                item = {
                    'id': f"item_{item_num:03d}",
                    'item_number': item_num,
                    'item_name': item_name.title(),
                    'section': current_section or 'UNKNOWN',
                    'price': price,
                    'currency': 'VND' if price else None,
                    'source': 'saigon.pdf',
                    'raw_text': item_text[:200]
                }
                item = add_dietary_tags(item)
                items.append(item)
        
        i += 1
    
    return items


def add_dietary_tags(item: Dict) -> Dict:
    """Add dietary and category tags"""
    tags = []
    name_lower = item['item_name'].lower()
    
    # Vegetarian keywords
    veg_keywords = [
        'lassi', 'milk', 'buttermilk', 'horlicks', 'boost', 'juice', 
        'tea', 'kaapi', 'coffee', 'raagi', 'raita', 'vegetable', 
        'paneer', 'dal', 'rice', 'bread', 'naan', 'roti', 'dosa',
        'idly', 'vada', 'bonda', 'pongal', 'bath', 'kulcha', 'salad',
        'rasam', 'sambar', 'chutney', 'uthappam', 'parotta', 'poori',
        'chappathi', 'pakoda', 'bhajji', 'sharbath', 'panagam', 'neer',
        'nannari', 'soda', 'water', 'mineral'
    ]
    
    if any(kw in name_lower for kw in veg_keywords):
        tags.append('vegetarian')
    
    # Non-vegetarian keywords
    non_veg_keywords = [
        'mutton', 'chicken', 'fish', 'prawn', 'egg', 'meat', 'tikka', 
        'biryani', 'meen', 'varuval', 'chukka'
    ]
    
    if any(kw in name_lower for kw in non_veg_keywords):
        tags.append('non-vegetarian')
    
    # Beverage keywords
    beverage_keywords = [
        'juice', 'lassi', 'tea', 'coffee', 'kaapi', 'beer', 'wine', 
        'cocktail', 'mocktail', 'liquor', 'rum', 'vodka', 'whisky', 
        'whiskey', 'gin', 'chivas', 'bacardi', 'smirnoff', 'horlicks',
        'boost', 'soda', 'water', 'sharbath', 'panagam'
    ]
    
    if any(kw in name_lower for kw in beverage_keywords):
        tags.append('beverage')
    
    item['tags'] = tags if tags else ['unknown']
    return item


def process_menu_data(pdf_path: str, output_path: str):
    """Main processing function"""
    print(f"📄 Extracting text from {pdf_path}...")
    full_text = extract_all_text(pdf_path)
    full_text = normalize_text(full_text)
    print(f"   Extracted {len(full_text)} characters from PDF")
    
    print(f"🔍 Parsing menu items...")
    items = parse_all_items(full_text)
    
    # Remove duplicates (keep first occurrence)
    seen = {}
    unique_items = []
    for item in items:
        num = item['item_number']
        if num not in seen:
            seen[num] = item
            unique_items.append(item)
    
    items = sorted(unique_items, key=lambda x: x['item_number'])
    
    # Save to JSON
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Processed {len(items)} menu items")
    print(f"✅ Saved to {output_path}")
    
    # Print summary
    sections = {}
    for item in items:
        section = item['section']
        sections[section] = sections.get(section, 0) + 1
    
    print(f"\n📊 Sections found: {len(sections)}")
    for section, count in sorted(sections.items()):
        print(f"   - {section}: {count} items")
    
    # Statistics
    with_price = sum(1 for item in items if item.get('price'))
    with_tags = sum(1 for item in items if item.get('tags') and item['tags'] != ['unknown'])
    
    print(f"\n📈 Statistics:")
    print(f"   - Items with price: {with_price}/{len(items)} ({with_price/len(items)*100:.1f}%)")
    print(f"   - Items without price: {len(items) - with_price}")
    print(f"   - Items with tags: {with_tags}/{len(items)}")
    
    # Show sample items
    print(f"\n📋 Sample items (first 20):")
    for item in items[:20]:
        price = item.get('price')
        if price is None:
            price_str = "N/A"
        else:
            try:
                price_str = f"{float(price):,.0f}"
            except (TypeError, ValueError):
                price_str = str(price)
        section_short = item['section'][:20] if len(item['section']) > 20 else item['section']
        print(f"   {item['item_number']:3d}. {item['item_name']:45s} | {price_str:>10s} | {section_short}")
    
    return items


if __name__ == "__main__":
    project_root = Path(__file__).parent.parent
    pdf_path = project_root / "saigon.pdf"
    output_path = project_root / "data" / "processed" / "menu_items.json"
    process_menu_data(str(pdf_path), str(output_path))

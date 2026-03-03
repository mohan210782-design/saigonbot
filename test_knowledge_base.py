#!/usr/bin/env python3
"""
Test script for Knowledge Base functionality
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from knowledge_base import get_knowledge_base

def test_knowledge_base():
    """Test knowledge base loading and retrieval"""
    print("=" * 60)
    print("Testing Knowledge Base")
    print("=" * 60)
    
    kb = get_knowledge_base()
    
    # Test location
    print("\n📍 Location:")
    location = kb.get_location()
    if location:
        print(f"  Restaurant: {location.get('restaurant_name')}")
        print(f"  Address: {location.get('address', {}).get('full_address')}")
    else:
        print("  ❌ Location not found")
    
    # Test hours
    print("\n🕒 Hours:")
    hours = kb.get_hours()
    if hours:
        print(f"  Summary: {hours.get('summary')}")
    else:
        print("  ❌ Hours not found")
    
    # Test contact
    print("\n📞 Contact:")
    contact = kb.get_contact()
    if contact:
        print(f"  Phone: {contact.get('phone', {}).get('formatted')}")
        print(f"  Email: {contact.get('email')}")
    else:
        print("  ❌ Contact not found")
    
    # Test reservations
    print("\n📅 Reservations:")
    reservations = kb.get_reservation_info()
    if reservations:
        print("  ✅ Reservation info loaded")
    else:
        print("  ❌ Reservations not found")
    
    # Test formatted output
    print("\n" + "=" * 60)
    print("Formatted Restaurant Info:")
    print("=" * 60)
    formatted = kb.get_restaurant_info_text()
    print(formatted)
    
    print("\n✅ Knowledge base test complete!")

if __name__ == "__main__":
    test_knowledge_base()

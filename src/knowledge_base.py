"""
Knowledge Base Module
Loads and serves structured restaurant knowledge (location, hours, services, FAQ)
Separate from menu RAG - provides instant answers for restaurant info queries
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """Manages structured restaurant knowledge"""
    
    def __init__(self, kb_path: Optional[Path] = None):
        """
        Initialize knowledge base
        
        Args:
            kb_path: Path to knowledge base directory. Defaults to data/knowledge_base
        """
        if kb_path is None:
            project_root = Path(__file__).parent.parent
            kb_path = project_root / "data" / "knowledge_base"
        
        self.kb_path = Path(kb_path)
        self._data = {}
        self._load_all()
    
    def _load_all(self):
        """Load all knowledge base files"""
        try:
            # Load restaurant info
            self._load_restaurant_info()
            
            # Load services
            self._load_services()
            
            # Load FAQ
            self._load_faq()
            
            logger.info(f"✅ Knowledge base loaded from {self.kb_path}")
        except Exception as e:
            logger.error(f"⚠️  Failed to load knowledge base: {e}")
            self._data = {}
    
    def _load_restaurant_info(self):
        """Load restaurant information files"""
        restaurant_path = self.kb_path / "restaurant"
        
        if not restaurant_path.exists():
            logger.warning(f"Restaurant info directory not found: {restaurant_path}")
            return
        
        # Load location
        location_file = restaurant_path / "location.json"
        if location_file.exists():
            with open(location_file, 'r', encoding='utf-8') as f:
                self._data['location'] = json.load(f)
        
        # Load hours
        hours_file = restaurant_path / "hours.json"
        if hours_file.exists():
            with open(hours_file, 'r', encoding='utf-8') as f:
                self._data['hours'] = json.load(f)
        
        # Load contact
        contact_file = restaurant_path / "contact.json"
        if contact_file.exists():
            with open(contact_file, 'r', encoding='utf-8') as f:
                self._data['contact'] = json.load(f)
        
        # Load policies
        policies_file = restaurant_path / "policies.json"
        if policies_file.exists():
            with open(policies_file, 'r', encoding='utf-8') as f:
                self._data['policies'] = json.load(f)
        
        # Load accessibility
        accessibility_file = restaurant_path / "accessibility.json"
        if accessibility_file.exists():
            with open(accessibility_file, 'r', encoding='utf-8') as f:
                self._data['accessibility'] = json.load(f)
    
    def _load_services(self):
        """Load service information files"""
        services_path = self.kb_path / "services"
        
        if not services_path.exists():
            logger.warning(f"Services directory not found: {services_path}")
            return
        
        # Load reservations
        reservations_file = services_path / "reservations.json"
        if reservations_file.exists():
            with open(reservations_file, 'r', encoding='utf-8') as f:
                self._data['reservations'] = json.load(f)
        
        # Load events
        events_file = services_path / "events.json"
        if events_file.exists():
            with open(events_file, 'r', encoding='utf-8') as f:
                self._data['events'] = json.load(f)
        
        # Load catering
        catering_file = services_path / "catering.json"
        if catering_file.exists():
            with open(catering_file, 'r', encoding='utf-8') as f:
                self._data['catering'] = json.load(f)
        
        # Load delivery
        delivery_file = services_path / "delivery.json"
        if delivery_file.exists():
            with open(delivery_file, 'r', encoding='utf-8') as f:
                self._data['delivery'] = json.load(f)
    
    def _load_faq(self):
        """Load FAQ"""
        faq_path = self.kb_path / "faq" / "common_questions.json"
        
        if faq_path.exists():
            with open(faq_path, 'r', encoding='utf-8') as f:
                faq_data = json.load(f)
                self._data['faq'] = faq_data.get('faq_items', [])
    
    def get_location(self) -> Optional[Dict]:
        """Get restaurant location information"""
        return self._data.get('location')
    
    def get_hours(self) -> Optional[Dict]:
        """Get restaurant hours"""
        return self._data.get('hours')
    
    def get_contact(self) -> Optional[Dict]:
        """Get contact information"""
        return self._data.get('contact')
    
    def get_policies(self) -> Optional[Dict]:
        """Get restaurant policies"""
        return self._data.get('policies')
    
    def get_accessibility(self) -> Optional[Dict]:
        """Get accessibility information"""
        return self._data.get('accessibility')
    
    def get_reservation_info(self) -> Optional[Dict]:
        """Get reservation information"""
        return self._data.get('reservations')
    
    def get_events_info(self) -> Optional[Dict]:
        """Get events/booking information"""
        return self._data.get('events')
    
    def get_catering_info(self) -> Optional[Dict]:
        """Get catering information"""
        return self._data.get('catering')
    
    def get_delivery_info(self) -> Optional[Dict]:
        """Get delivery information"""
        return self._data.get('delivery')
    
    def get_faq(self) -> List[Dict]:
        """Get FAQ items"""
        return self._data.get('faq', [])
    
    def search_faq(self, query: str) -> List[Dict]:
        """
        Search FAQ for relevant questions
        
        Args:
            query: Search query
            
        Returns:
            List of matching FAQ items
        """
        query_lower = query.lower()
        faq_items = self.get_faq()
        
        matches = []
        for item in faq_items:
            question = item.get('question', '').lower()
            answer = item.get('answer', '').lower()
            
            # Simple keyword matching
            if any(word in question or word in answer for word in query_lower.split() if len(word) > 2):
                matches.append(item)
        
        return matches
    
    def format_location(self) -> str:
        """Format location as human-readable text"""
        location = self.get_location()
        if not location:
            return ""
        
        addr = location.get('address', {})
        return f"""📍 **{location.get('restaurant_name', 'Saigon Indian Restaurant')}**

{addr.get('full_address', '')}

We're located in the heart of District 1, making it convenient for both locals and visitors. Need directions or more information? Just ask! 😊"""
    
    def format_hours(self) -> str:
        """Format hours as human-readable text"""
        hours = self.get_hours()
        if not hours:
            return ""
        
        return f"""🕒 **Opening Hours**

{hours.get('summary', 'Monday – Sunday: 7:30 AM – 10:30 PM')}

{hours.get('note', 'We serve Breakfast, Lunch & Dinner throughout the day!')}

Whether you're looking for an early morning dosa or a late-night curry, we're here for you! 😊"""
    
    def format_contact(self) -> str:
        """Format contact info as human-readable text"""
        contact = self.get_contact()
        if not contact:
            return ""
        
        phone = contact.get('phone', {})
        return f"""📞 **Contact Information**

Phone: {phone.get('formatted', '')}

✉️ Email: {contact.get('email', '')}

Feel free to call us for reservations, inquiries, or any questions! We're happy to help! 😊"""
    
    def get_restaurant_info_text(self) -> str:
        """Get full restaurant information as formatted text"""
        parts = []
        
        location_text = self.format_location()
        if location_text:
            parts.append(location_text)
        
        hours_text = self.format_hours()
        if hours_text:
            parts.append(hours_text)
        
        contact_text = self.format_contact()
        if contact_text:
            parts.append(contact_text)
        
        return "\n\n".join(parts)


# Global knowledge base instance
_kb_instance = None


def get_knowledge_base() -> KnowledgeBase:
    """Get or create global knowledge base instance"""
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
    return _kb_instance

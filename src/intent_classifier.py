"""
Intent Classification System
Classifies user queries into specific intent categories for proper routing
"""
from typing import Dict, List, Optional, Tuple
from enum import Enum
import re


class IntentType(Enum):
    """Intent categories"""
    MENU_SEARCH = "menu_search"
    MENU_RECOMMENDATION = "menu_recommendation"
    MENU_PRICE = "menu_price"
    MENU_INGREDIENTS = "menu_ingredients"
    MENU_ALLERGEN = "menu_allergen"
    MENU_DIETARY = "menu_dietary"
    
    RESTAURANT_LOCATION = "restaurant_location"
    RESTAURANT_HOURS = "restaurant_hours"
    RESTAURANT_CONTACT = "restaurant_contact"
    RESTAURANT_ABOUT = "restaurant_about"
    RESTAURANT_PARKING = "restaurant_parking"
    RESTAURANT_ACCESSIBILITY = "restaurant_accessibility"
    
    SERVICE_RESERVATION = "service_reservation"
    SERVICE_RESERVATION_MODIFY = "service_reservation_modify"
    SERVICE_RESERVATION_CANCEL = "service_reservation_cancel"
    SERVICE_EVENT_BOOKING = "service_event_booking"
    SERVICE_CATERING = "service_catering"
    SERVICE_DELIVERY = "service_delivery"
    
    IDENTITY_WHO_ARE_YOU = "identity_who_are_you"
    IDENTITY_WHAT_DO_YOU_DO = "identity_what_do_you_do"
    IDENTITY_CAPABILITIES = "identity_capabilities"
    
    CONVERSATIONAL_GREETING = "conversational_greeting"
    CONVERSATIONAL_GRATITUDE = "conversational_gratitude"
    CONVERSATIONAL_SMALL_TALK = "conversational_small_talk"
    CONVERSATIONAL_COMPLAINT = "conversational_complaint"
    CONVERSATIONAL_FEEDBACK = "conversational_feedback"
    
    CLARIFICATION_NEEDED = "clarification_needed"
    OUT_OF_SCOPE = "out_of_scope"


class IntentCategory(Enum):
    """High-level intent categories"""
    MENU = "menu"
    RESTAURANT_INFO = "restaurant_info"
    SERVICE = "service"
    IDENTITY = "identity"
    CONVERSATIONAL = "conversational"
    CLARIFICATION = "clarification"
    OUT_OF_SCOPE = "out_of_scope"


class IntentResult:
    """Result of intent classification"""
    
    def __init__(
        self,
        intent_type: IntentType,
        confidence: float,
        category: IntentCategory,
        entities: Optional[Dict] = None,
        requires_clarification: bool = False
    ):
        self.intent_type = intent_type
        self.confidence = confidence
        self.category = category
        self.entities = entities or {}
        self.requires_clarification = requires_clarification
    
    def is_menu_intent(self) -> bool:
        """Check if this is a menu-related intent"""
        return self.category == IntentCategory.MENU
    
    def is_restaurant_info_intent(self) -> bool:
        """Check if this is a restaurant info intent"""
        return self.category == IntentCategory.RESTAURANT_INFO
    
    def is_service_intent(self) -> bool:
        """Check if this is a service intent"""
        return self.category == IntentCategory.SERVICE
    
    def is_identity_intent(self) -> bool:
        """Check if this is an identity intent"""
        return self.category == IntentCategory.IDENTITY
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging"""
        return {
            "intent_type": self.intent_type.value,
            "confidence": self.confidence,
            "category": self.category.value,
            "entities": self.entities,
            "requires_clarification": self.requires_clarification
        }


class IntentClassifier:
    """Classifies user queries into intent categories"""
    
    def __init__(self):
        """Initialize intent classifier with pattern definitions"""
        self._build_patterns()
    
    def _build_patterns(self):
        """Build pattern dictionaries for intent detection"""
        
        # Identity patterns
        self.identity_patterns = {
            IntentType.IDENTITY_WHO_ARE_YOU: [
                r'\bwho\s+are\s+you\b',
                r'\bwho\s+is\s+chikku\b',
                r'\bwhat\s+is\s+chikku\b',
                r'\bintroduce\s+yourself\b',
                r'\btell\s+me\s+about\s+yourself\b'
            ],
            IntentType.IDENTITY_WHAT_DO_YOU_DO: [
                r'\bwhat\s+(do|can)\s+you\s+do\b',
                r'\bwhat\s+is\s+your\s+role\b',
                r'\bwhat\s+are\s+your\s+capabilities\b',
                r'\bhow\s+can\s+you\s+help\b',
                r'\bwhat\s+services\s+do\s+you\s+provide\b',
                r'\bwhat\s+help\s+can\s+you\s+provide\b'
            ],
            IntentType.IDENTITY_CAPABILITIES: [
                r'\bwhat\s+can\s+you\s+help\s+with\b',
                r'\bwhat\s+are\s+you\s+capable\s+of\b',
                r'\bwhat\s+do\s+you\s+know\b'
            ]
        }
        
        # Restaurant info patterns
        self.restaurant_info_patterns = {
            IntentType.RESTAURANT_LOCATION: [
                r'\bwhere\s+(are\s+you|is\s+the\s+restaurant)\b',
                r'\baddress\b',
                r'\blocation\b',
                r'\bwhere\s+is\s+saigon\s+indian\b',
                r'\bhow\s+to\s+reach\b',
                r'\bdirections\b',
                r'\bwhere\s+are\s+you\s+located\b',
                r'\bwhere\s+exactly\s+are\s+you\s+located\b'
            ],
            IntentType.RESTAURANT_HOURS: [
                r'\b(opening|closing)\s+hours\b',
                r'\bwhat\s+time\s+(do\s+you\s+open|are\s+you\s+open|do\s+you\s+close)\b',
                r'\bwhen\s+(are\s+you\s+open|do\s+you\s+close)\b',
                r'\btimings\b',
                r'\bhours\b',
                r'\bopen\s+until\b',
                r'\bclose\s+at\b',
                r'\bwhat\s+time\s+do\s+you\s+close\b',
                r'\bwhen\s+do\s+you\s+close\b',
                r'\bdo\s+you\s+serve\s+(breakfast|lunch|dinner)\b'
            ],
            IntentType.RESTAURANT_CONTACT: [
                r'\bphone\s+number\b',
                r'\bcontact\s+(number|info)\b',
                r'\bcall\s+you\b',
                r'\bemail\b',
                r'\bphone\b',
                r'\btelephone\b',
                r'\bhow\s+to\s+contact\b'
            ],
            IntentType.RESTAURANT_ABOUT: [
                r'\btell\s+me\s+about\s+(saigon\s+indian|the\s+restaurant)\b',
                r'\babout\s+saigon\s+indian\b',
                r'\babout\s+the\s+restaurant\b',
                r'\bwhat\s+is\s+saigon\s+indian\b',
                r'\binfo\s+about\s+the\s+restaurant\b'
            ],
            IntentType.RESTAURANT_PARKING: [
                r'\bparking\b',
                r'\bpark\s+car\b',
                r'\bparking\s+available\b',
                r'\bwhere\s+to\s+park\b'
            ],
            IntentType.RESTAURANT_ACCESSIBILITY: [
                r'\bwheelchair\b',
                r'\baccessible\b',
                r'\bdisability\b',
                r'\baccessibility\b'
            ]
        }
        
        # Service patterns
        self.service_patterns = {
            IntentType.SERVICE_RESERVATION: [
                r'\b(book|reserve)\s+(a\s+)?table\b',
                r'\bmake\s+a\s+reservation\b',
                r'\breservation\b',
                r'\bbooking\b',
                r'\bwant\s+to\s+book\b',
                r'\bneed\s+a\s+table\b'
            ],
            IntentType.SERVICE_RESERVATION_MODIFY: [
                r'\b(modify|change|update)\s+reservation\b',
                r'\bchange\s+booking\b',
                r'\bmodify\s+booking\b'
            ],
            IntentType.SERVICE_RESERVATION_CANCEL: [
                r'\b(cancel|delete)\s+reservation\b',
                r'\bcancel\s+booking\b'
            ],
            IntentType.SERVICE_EVENT_BOOKING: [
                r'\bevent\s+booking\b',
                r'\bprivate\s+dining\b',
                r'\bcorporate\s+event\b',
                r'\bparty\s+booking\b',
                r'\bdo\s+you\s+do\s+party\s+bookings\b',
                r'\bparty\s+bookings\b'
            ],
            IntentType.SERVICE_CATERING: [
                r'\bcatering\b',
                r'\bfood\s+delivery\s+for\s+event\b'
            ],
            IntentType.SERVICE_DELIVERY: [
                r'\bdelivery\b',
                r'\bhome\s+delivery\b',
                r'\bdeliver\s+food\b'
            ]
        }
        
        # Menu patterns
        self.menu_patterns = {
            IntentType.MENU_SEARCH: [
                r'\b(show|find|search|list|what|which)\s+.*\b(dishes?|items?|food|menu)\b',
                r'\b.*\s+(options?|available|have|offer)\b',
                r'\bmenu\s+items?\b',
                r'\badd\s+one\b',
                r'\bgive\s+me\s+one\b',
                r'\bi.*ll\s+take\b',
                r'\bmake\s+it\s+(less|more)\s+spicy\b',
                r'\bsomething\s+(spicy|creamy|tangy|rich|filling)\b',
                r'\bnot\s+too\s+(oily|spicy)\b'
            ],
            IntentType.MENU_RECOMMENDATION: [
                r'\brecommend\b',
                r'\bsuggest\b',
                r'\bwhat\s+should\s+I\s+(order|try|have)\b',
                r'\bbest\s+(dish|item|non.*veg|veg)\b',
                r'\bpopular\s+(dish|item)\b',
                r'\bchef.*special\b',
                r'\bchef.*recommendation\b',
                r'\bwhat.*recommend\b',
                r'\bwhat.*best\b',
                r'\bwhat.*popular\b',
                r'\bwhich.*popular\b',
                r'\bwhich.*best\b',
                r'\bspiciest\b',
                r'\bwhat.*spiciest\b',
                r'\bsomething\s+special\b',
                r'\bsurprise\s+me\b',
                r'\breally\s+hungry\b',
                r'\bsomething\s+comforting\b',
                r'\bsomething\s+filling\b',
                r'\bsomething\s+rich\s+and\s+creamy\b',
                r'\bsomething\s+kids\s+will\s+like\b',
                r'\bgood\s+in\s+(mutton|chicken|fish)\b',
                r'\bwhat.*good\s+in\b',
                r'\bstrong\s+indian\s+masala\b'
            ],
            IntentType.MENU_PRICE: [
                r'\b(price|cost|how\s+much)\s+.*\b',
                r'\b.*\s+(price|cost)\b',
                r'\bhow\s+much\s+(is|does|for)\b'
            ],
            IntentType.MENU_INGREDIENTS: [
                r'\bingredients?\b',
                r'\bwhat.*made\s+of\b',
                r'\bcontains?\b'
            ],
            IntentType.MENU_ALLERGEN: [
                r'\ballergen\b',
                r'\ballergy\b',
                r'\bcontains?\s+(nuts|gluten|dairy)\b'
            ],
            IntentType.MENU_DIETARY: [
                r'\b(vegetarian|vegan|jain|gluten.*free|halal)\b',
                r'\bnon.*vegetarian\b',
                r'\bdietary\b'
            ]
        }
        
        # Conversational patterns
        self.conversational_patterns = {
            IntentType.CONVERSATIONAL_GREETING: [
                r'\b(hello|hi|hey|namaste|good\s+(morning|afternoon|evening))\b',
                r'\bgreetings?\b'
            ],
            IntentType.CONVERSATIONAL_GRATITUDE: [
                r'\b(thank\s+you|thanks|appreciate)\b'
            ],
            IntentType.CONVERSATIONAL_SMALL_TALK: [
                r'\bhow\s+are\s+you\b',
                r'\bhow.*doing\b'
            ],
            IntentType.CONVERSATIONAL_COMPLAINT: [
                r'\b(complaint|problem|issue|wrong|bad)\b'
            ],
            IntentType.CONVERSATIONAL_FEEDBACK: [
                r'\b(feedback|review|rating|opinion)\b'
            ]
        }
    
    def classify_intent(self, query: str) -> IntentResult:
        """
        Classify user query into intent category
        
        Args:
            query: User's query string
            
        Returns:
            IntentResult with intent type, confidence, and category
        """
        query_lower = query.lower().strip()
        
        # Check each intent category in priority order
        # Identity first (highest priority)
        result = self._check_identity_intent(query_lower)
        if result:
            return result
        
        # Restaurant info
        result = self._check_restaurant_info_intent(query_lower)
        if result:
            return result
        
        # Service
        result = self._check_service_intent(query_lower)
        if result:
            return result
        
        # Conversational
        result = self._check_conversational_intent(query_lower)
        if result:
            return result
        
        # Menu (default if contains food-related keywords)
        result = self._check_menu_intent(query_lower)
        if result:
            return result
        
        # If no clear intent, mark as clarification needed
        return IntentResult(
            intent_type=IntentType.CLARIFICATION_NEEDED,
            confidence=0.3,
            category=IntentCategory.CLARIFICATION,
            requires_clarification=True
        )
    
    def _check_identity_intent(self, query: str) -> Optional[IntentResult]:
        """Check for identity-related intents"""
        for intent_type, patterns in self.identity_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    category = IntentCategory.IDENTITY
                    return IntentResult(
                        intent_type=intent_type,
                        confidence=0.95,
                        category=category
                    )
        return None
    
    def _check_restaurant_info_intent(self, query: str) -> Optional[IntentResult]:
        """Check for restaurant info intents"""
        for intent_type, patterns in self.restaurant_info_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    category = IntentCategory.RESTAURANT_INFO
                    return IntentResult(
                        intent_type=intent_type,
                        confidence=0.9,
                        category=category
                    )
        return None
    
    def _check_service_intent(self, query: str) -> Optional[IntentResult]:
        """Check for service intents"""
        for intent_type, patterns in self.service_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    category = IntentCategory.SERVICE
                    return IntentResult(
                        intent_type=intent_type,
                        confidence=0.9,
                        category=category
                    )
        return None
    
    def _check_conversational_intent(self, query: str) -> Optional[IntentResult]:
        """Check for conversational intents"""
        for intent_type, patterns in self.conversational_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    category = IntentCategory.CONVERSATIONAL
                    return IntentResult(
                        intent_type=intent_type,
                        confidence=0.85,
                        category=category
                    )
        return None
    
    def _check_menu_intent(self, query: str) -> Optional[IntentResult]:
        """Check for menu-related intents"""
        # Check for specific menu intents first
        for intent_type, patterns in self.menu_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query, re.IGNORECASE):
                    category = IntentCategory.MENU
                    return IntentResult(
                        intent_type=intent_type,
                        confidence=0.85,
                        category=category
                    )
        
        # Check for food-related keywords (fallback)
        food_keywords = [
            'biryani', 'dosa', 'curry', 'naan', 'tandoori', 'paneer',
            'vegetarian', 'non-vegetarian', 'vegan', 'spicy', 'mild',
            'starter', 'main', 'dessert', 'drink', 'beverage',
            'breakfast', 'lunch', 'dinner', 'appetizer'
        ]
        
        if any(keyword in query for keyword in food_keywords):
            return IntentResult(
                intent_type=IntentType.MENU_SEARCH,
                confidence=0.7,
                category=IntentCategory.MENU
            )
        
        return None


# Global instance
_intent_classifier = None


def get_intent_classifier() -> IntentClassifier:
    """Get or create global intent classifier instance"""
    global _intent_classifier
    if _intent_classifier is None:
        _intent_classifier = IntentClassifier()
    return _intent_classifier

"""
Response Templates for deterministic responses
Prevents LLM hallucinations for common queries
"""
from typing import Dict, Optional
from intent_classifier import IntentType


# Welcome message (shown once per session)
WELCOME_MESSAGE = """🌟 *Namaste & Welcome!* 🌟

I'm *Chikku*, your personal food companion, flavor guide, and menu expert at Saigon Indian Restaurant. Think of me as your friendly in-house foodie who knows every spice, every secret recipe, and every chef's special on our menu!

Welcome to *Saigon Indian Restaurant* — where the rich flavors of India meet warm hospitality in the heart of the city. 🇮🇳✨

At Saigon Indian Restaurant, every dish is crafted with authentic Indian spices, traditional recipes, and a passion for great food. From aromatic biryanis and creamy curries to sizzling tandoori specialties and freshly baked naan, each meal is prepared to deliver a true taste of India.

Craving something creamy and comforting?
Want it extra spicy? 🌶️
Looking for vegan, Jain, gluten-free, or kid-friendly options?
Planning a romantic dinner or a big family feast?

Just tell me your mood — and I'll surprise you with the perfect dish!

🍽️ I can help you:

* Explore our full menu with detailed descriptions
* Recommend chef's specials and customer favorites
* Customize dishes based on your taste preferences
* Suggest the best starters, mains, breads, and desserts combo
* Pair your meal with refreshing drinks
* Answer any questions about ingredients and spice levels

Whether you love rich North Indian curries, sizzling tandoori delights, or comforting biryanis, I'll make sure your experience at *Saigon Indian Restaurant* is unforgettable.

💬 Just talk to me like you would to a friend.
Tell me what you're craving… and let me take care of the rest.

Ready to discover your next favorite dish? 😍🍽️"""


# Identity responses
IDENTITY_RESPONSES = {
    IntentType.IDENTITY_WHO_ARE_YOU: WELCOME_MESSAGE,
    
    IntentType.IDENTITY_WHAT_DO_YOU_DO: """I'm Chikku, your personal food companion, flavor guide, and menu expert at Saigon Indian Restaurant! 😊

I help you:
• Discover dishes that match your taste and dietary preferences
• Find vegetarian, vegan, gluten-free, and other special dietary options
• Get recommendations for the perfect meal
• Learn about our menu items, ingredients, and prices
• Answer questions about our restaurant (location, hours, contact info)
• Help with reservations and special requests

Think of me as your friendly in-house foodie who knows every dish on our menu! What would you like to explore today? 🍽️""",
    
    IntentType.IDENTITY_CAPABILITIES: """I can help you with:

🍽️ **Menu Discovery**
• Find dishes by name, ingredients, or dietary preferences
• Get recommendations based on your mood
• Learn about prices and ingredients
• Discover chef's specials and popular items

📍 **Restaurant Information**
• Location and directions
• Opening hours
• Contact information
• Parking and accessibility

📞 **Services**
• Table reservations
• Event bookings
• Catering inquiries
• Delivery information

Just tell me what you're looking for, and I'll help you find it! 😊"""
}


# Restaurant info responses
RESTAURANT_INFO_RESPONSES = {
    IntentType.RESTAURANT_LOCATION: """📍 **Saigon Indian Restaurant**

26 Lê Anh Xuân Street,
Ward Bến Thành, District 1
Ho Chi Minh City, Vietnam 🇻🇳

We're located in the heart of District 1, making it convenient for both locals and visitors. Need directions or more information? Just ask! 😊""",
    
    IntentType.RESTAURANT_HOURS: """🕒 **Opening Hours**

Monday – Sunday: 7:30 AM – 10:30 PM

We serve Breakfast, Lunch & Dinner throughout the day!

Whether you're looking for an early morning dosa or a late-night curry, we're here for you! 😊""",
    
    IntentType.RESTAURANT_CONTACT: """📞 **Contact Information**

Phone: +84 (028) 6291 3672
       +84 (028) 3824 5671

✉️ Email: saigonindiarestaurant@gmail.com

Feel free to call us for reservations, inquiries, or any questions! We're happy to help! 😊""",
    
    IntentType.RESTAURANT_ABOUT: """Welcome to Saigon Indian Restaurant! 🇮🇳✨

We're a premium Indian dining destination in the heart of Ho Chi Minh City, bringing together authentic South and North Indian cuisine with warm hospitality.

**What makes us special:**
• Authentic flavors from across India
• High-quality ingredients and traditional cooking techniques
• Warm, attentive service
• Perfect for family dinners, celebrations, and business gatherings

Whether you're craving fragrant biryanis, crispy dosas, creamy curries, or freshly baked breads, we deliver the true flavors of Indian gastronomy.

Ready to explore our menu? Just tell me what you're in the mood for! 😊""",
    
    IntentType.RESTAURANT_PARKING: """🅿️ **Parking Information**

We're located in District 1, Ho Chi Minh City. While we don't have dedicated parking, there are several parking options nearby:

• Street parking (subject to availability)
• Nearby parking lots within walking distance
• Public transportation is convenient (we're in a central location)

For the best parking options, I'd recommend calling us at +84 (028) 6291 3672, and our team can guide you to the nearest parking! 😊""",
    
    IntentType.RESTAURANT_ACCESSIBILITY: """♿ **Accessibility**

We're committed to making our restaurant accessible to all guests. Our restaurant is located on the ground floor with easy access.

For specific accessibility needs or questions, please call us at +84 (028) 6291 3672, and we'll be happy to assist you and ensure your visit is comfortable! 😊"""
}


# Service responses
SERVICE_RESPONSES = {
    IntentType.SERVICE_RESERVATION: """I'd be happy to help you make a reservation! 📞

**To book a table, you can:**

Call us directly at:
📞 +84 (028) 6291 3672
📞 +84 (028) 3824 5671

**Or tell me:**
• What date you'd like to book
• What time
• How many people
• Any special requests or dietary preferences

And I'll guide you through the reservation process! 😊""",
    
    IntentType.SERVICE_RESERVATION_MODIFY: """I can help you modify your reservation! 📞

Please call us at:
📞 +84 (028) 6291 3672
📞 +84 (028) 3824 5671

Our team will be happy to help you change your booking details. 

Or tell me what you'd like to change, and I can guide you! 😊""",
    
    IntentType.SERVICE_RESERVATION_CANCEL: """I can help you cancel your reservation. 📞

Please call us at:
📞 +84 (028) 6291 3672
📞 +84 (028) 3824 5671

Our team will assist you with the cancellation.

We hope to serve you another time! 😊""",
    
    IntentType.SERVICE_EVENT_BOOKING: """We'd love to host your event! 🎉

**We offer:**
• Corporate events
• Private dining
• Parties and celebrations
• Conferences & seminars

For event bookings, please call us at:
📞 +84 (028) 6291 3672
📞 +84 (028) 3824 5671

Our team can customize menus and arrangements to make your event memorable! Tell me what kind of event you're planning, and I can help! 😊""",
    
    IntentType.SERVICE_CATERING: """We offer catering services! 🍽️

For catering inquiries and custom menus, please call us at:
📞 +84 (028) 6291 3672
📞 +84 (028) 3824 5671

We can tailor our menu to your event needs. Tell me about your event, and I can help guide you! 😊""",
    
    IntentType.SERVICE_DELIVERY: """We offer delivery services! 🚚

For delivery orders, please call us at:
📞 +84 (028) 6291 3672
📞 +84 (028) 3824 5671

Our team will be happy to help you place your order and arrange delivery to your location.

What would you like to order? I can help you explore our menu! 🍽️"""
}


# Conversational responses
CONVERSATIONAL_RESPONSES = {
    IntentType.CONVERSATIONAL_GREETING: [
        "Hello! Welcome to Saigon Indian Restaurant! How can I help you today? 😊",
        "Hi there! I'm Chikku, ready to help you discover our menu. What are you craving? 🍽️",
        "Namaste! Welcome! I'm here to help you find the perfect dish. What can I do for you? 😊",
        "Hey! Great to see you! What would you like to explore from our menu today? 🍽️"
    ],
    
    IntentType.CONVERSATIONAL_GRATITUDE: [
        "You're very welcome! Happy to help! 😊",
        "My pleasure! Is there anything else I can help you with? 😊",
        "You're welcome! Enjoy your meal! 🍽️",
        "Happy to help! Feel free to ask if you need anything else! 😊"
    ],
    
    IntentType.CONVERSATIONAL_SMALL_TALK: [
        "I'm doing great, thank you for asking! Ready to help you discover our delicious menu. What are you in the mood for? 😊",
        "I'm wonderful! How about you? What brings you to Saigon Indian Restaurant today? 😊",
        "I'm doing fantastic! Excited to help you find your perfect dish. What would you like to explore? 🍽️"
    ],
    
    IntentType.CONVERSATIONAL_COMPLAINT: """I'm sorry to hear about your concern. 😔

To help resolve this quickly, please call us at:
📞 +84 (028) 6291 3672
📞 +84 (028) 3824 5671

Our team will be happy to address your concern and make things right.

Can you tell me more about what happened? I can help guide you! 😊""",
    
    IntentType.CONVERSATIONAL_FEEDBACK: """We'd love to hear your feedback! 😊

You can share your feedback by:
• Calling us at +84 (028) 6291 3672
• Emailing us at saigonindiarestaurant@gmail.com
• Sharing it with me right here!

Your feedback helps us serve you better. What would you like to share? 😊"""
}


# Error and clarification responses
ERROR_RESPONSES = {
    'no_menu_results': "I couldn't find that in our current menu, but I'd be happy to suggest something similar. Could you tell me what type of dish you're looking for? 😊",
    
    'clarification_needed': """I'd love to help you! Could you tell me a bit more about what you're looking for?

I can help you with:
• Exploring our menu and dishes
• Restaurant information (location, hours, contact)
• Making reservations
• Answering questions about ingredients and dietary preferences

What would you like to know? 😊""",
    
    'system_error': "I'm having a bit of trouble right now. Please try again in a moment, or call us at +84 (028) 6291 3672 for immediate assistance. 😊"
}


def get_template(intent_type: IntentType) -> Optional[str]:
    """
    Get template response for given intent type.
    Returns None if no template exists (should use LLM).
    """
    # Check identity responses
    if intent_type in IDENTITY_RESPONSES:
        return IDENTITY_RESPONSES[intent_type]
    
    # Check restaurant info responses
    if intent_type in RESTAURANT_INFO_RESPONSES:
        return RESTAURANT_INFO_RESPONSES[intent_type]
    
    # Check service responses
    if intent_type in SERVICE_RESPONSES:
        return SERVICE_RESPONSES[intent_type]
    
    # Check conversational responses (random selection for variety)
    if intent_type in CONVERSATIONAL_RESPONSES:
        responses = CONVERSATIONAL_RESPONSES[intent_type]
        if isinstance(responses, list):
            import random
            return random.choice(responses)
        return responses
    
    return None


def get_welcome_message() -> str:
    """Get welcome message template"""
    return WELCOME_MESSAGE


def get_error_response(error_type: str) -> str:
    """Get error response template"""
    return ERROR_RESPONSES.get(error_type, ERROR_RESPONSES['system_error'])

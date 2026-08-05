"""
Response Templates for Chikku Robotics
Deterministic responses to prevent LLM hallucinations.
"""
from typing import Optional
from intent_classifier import IntentType


# ============================================================
# ROBOTICS TEMPLATES (Chikku Robotics)
# ============================================================

ROBOTICS_WELCOME_MESSAGE = """*Hello! I'm Chikku!* 🤖

I'm an intelligent service robot representing *Chikku Robotics*.

💡 I can tell you all about:

* Our hardware — service robots, cobots, drones, and autonomous vehicles.
* Our AI & software — Machine Learning, Computer Vision, Generative AI.
* Industry solutions — smart manufacturing, healthcare, warehousing, smart cities.

What would you like to explore?"""

ROBOTICS_IDENTITY_RESPONSES = {
    IntentType.IDENTITY_WHO_ARE_YOU: ROBOTICS_WELCOME_MESSAGE,

    IntentType.IDENTITY_WHAT_DO_YOU_DO: """I'm Chikku, an intelligent service robot from Chikku Robotics! 🤖

I'm here to share everything about our work in AI and robotics:

* Our hardware products — service robots, cobots, drones, autonomous vehicles.
* Our AI platforms — Machine Learning, Computer Vision, Generative AI.
* Industry solutions for manufacturing, healthcare, warehousing, and smart cities.

What would you like to explore?""",

    IntentType.IDENTITY_CAPABILITIES: """I can tell you all about Chikku Robotics! 🤖

*Hardware & Products*
* Service robots, collaborative robots, drones, autonomous vehicles.
* Electronic systems, sensors, and embedded devices.

*AI & Software*
* Artificial Intelligence, Machine Learning, Computer Vision.
* Generative AI, edge AI solutions, cloud platforms.

 *Industry Solutions*
* Smart manufacturing, healthcare, warehousing, smart cities.
* Consulting, engineering support, and training programs.

 *Innovation*
* R&D labs, patents, university and government partnerships.

What are you most curious about?""",
}

ROBOTICS_CONVERSATIONAL_RESPONSES = {
    IntentType.CONVERSATIONAL_GREETING: [
        "Hello! I'm Chikku from Chikku Robotics! What would you like to know about our intelligent robots? 🤖",
        "Hi there! I'm Chikku, your guide to all things AI and robotics. What can I share with you today?",
        "Hey! Great to meet you! I'm Chikku from Chikku Robotics. Curious about our technology? Just ask! 🤖",
    ],
    IntentType.CONVERSATIONAL_GRATITUDE: [
        "You're welcome! Happy to share our passion for robotics! 🤖",
        "My pleasure! Anything else you'd like to know about Chikku Robotics?",
        "Happy to help! Feel free to ask anything about our AI and robotics work! 😊",
    ],
    IntentType.CONVERSATIONAL_FAREWELL: [
        "Goodbye! It was great chatting with you about robotics and AI. Feel free to come back anytime you have questions! 🤖👋",
        "See you later! I'm always here if you want to explore more about Chikku Robotics. Take care! 👋😊",
        "Bye bye! Thanks for stopping by — the world of intelligent robots is always exciting. Until next time! 🤖✨",
        "Take care! If you ever want to learn more about our robots, AI, or solutions, I'm just a message away. Goodbye! 👋",
        "Farewell! Remember, the future is intelligent and we're building it together at Chikku Robotics. See you soon! 🚀👋",
    ],
    IntentType.CONVERSATIONAL_SMALL_TALK: [
        # "How are you" type
        "I'm doing great! Ready to chat about robots, AI, and smart technology. What are you curious about? 🤖",
        "I'm fantastic! Always excited to talk about Chikku Robotics. What would you like to explore?",
        # Polite declines ("no thank", "no thanks", "nope", "nah")
        "No problem at all! I'm here whenever you have questions about robotics and AI. Just ask! 🤖",
        "Alright! If you ever want to explore our intelligent robots or AI technology, I'm just a message away. 😊",
        "Sure thing! Feel free to reach out anytime you're curious about Chikku Robotics. 👋",
        # Casual acknowledgments ("ok", "sure", "yeah", "cool", "great")
        "Great! What would you like to know about Chikku Robotics? Our robots, AI, or industry solutions? 🤖",
        "Awesome! I'm here to share everything about intelligent robots. What interests you?",
        "Cool! Ready to dive into the world of robotics and AI? Just let me know what you'd like to explore! 😊",
        # General small talk
        "I'm all ears! Ask me anything about Chikku Robotics — our products, technology, or vision. 🤖",
        "Always happy to chat! What aspect of robotics and AI fascinates you the most?",
    ],
    IntentType.CONVERSATIONAL_COMPLAINT: "I appreciate you sharing your concern. While I'm here to chat about Chikku Robotics, I'd recommend reaching out to our team directly for any issues. Is there anything about our technology I can help with? 🤖",
    IntentType.CONVERSATIONAL_FEEDBACK: "We'd love to hear your thoughts! Your feedback helps us build better robots. Feel free to share, or reach out to us at info@chikkurobotics.com. What's on your mind? 🤖",
}

# ============================================================
# ROBOTICS COMPANY INFO TEMPLATES (Location, Contact, Hours, About)
# Used as fallback when knowledge base data is unavailable
# ============================================================

ROBOTICS_INFO_RESPONSES = {
    IntentType.RESTAURANT_LOCATION: """📍 **Chikku Robotics — Our Locations**

🏢 **Headquarters**: India

🌍 **Global Offices & R&D Labs**:
* Ho Chi Minh City, Vietnam.
* Tamil Nadu, India.

We serve customers globally through our direct sales team and partner network.

Would you like to know more about our specific office locations or how to get in touch? 🌐""",

    IntentType.RESTAURANT_CONTACT: """📞 **Contact Chikku Robotics**

✉️ Email: info@chikkurobotics.com

🌐 The best way to get started is with our Automation Readiness Assessment — a free consultation where we evaluate your operations and identify automation opportunities.

Feel free to reach out to us! We're happy to help with any questions about our AI and robotics solutions. 🤖""",

    IntentType.RESTAURANT_HOURS: """🕒 **Chikku Robotics — Business Hours**

Our offices and R&D labs operate during standard business hours (Monday-Friday, 9:00 AM - 6:00 PM local time).

For specific inquiries or to schedule a consultation, please reach out to us at info@chikkurobotics.com. We're happy to help! 😊""",

    IntentType.RESTAURANT_ABOUT: """Welcome to **Chikku Robotics**! 🤖✨

We design and manufacture intelligent robots for a smarter future. Our mission is to make advanced robotics and AI technology approachable, beneficial, and accessible to businesses and society worldwide.

**What we do:**
* 🤖 **Hardware**: Service robots, collaborative robots (cobots), autonomous vehicles, drones, embedded electronics & sensors.
* 🧠 **AI & Software**: Chikku Brain AI platform — deep learning, computer vision, NLP, generative AI, edge computing.
* 🏭 **Industry Solutions**: Smart manufacturing, healthcare, warehousing & logistics, smart cities, agriculture, hospitality, retail.
* 🔬 **Innovation**: R&D labs in Vietnam & India, 50+ patents, university & government partnerships.

I'm Chikku, your intelligent guide. What would you like to explore about our technology? 🌟""",
}

ROBOTICS_ERROR_RESPONSES = {
    'no_menu_results': "I couldn't find specific details on that, but I'd love to tell you about Chikku Robotics! What aspect of our AI and robotics work interests you? 🤖",
    'clarification_needed': """I'd love to help! I can tell you about:

* Our hardware products and robotic systems
* AI, Machine Learning, and Computer Vision platforms
* Industry solutions for manufacturing and healthcare
* Our R&D and global partnerships

What would you like to know? 🤖""",
    'system_error': "I'm having a bit of trouble right now. Please try again in a moment, or reach out to us at info@chikkurobotics.com. 😊",
}


def get_template(intent_type: IntentType) -> Optional[str]:
    """
    Get template response for given intent type (robotics-only).
    Returns None if no template exists (should use LLM).
    """
    if intent_type in ROBOTICS_IDENTITY_RESPONSES:
        return ROBOTICS_IDENTITY_RESPONSES[intent_type]
    if intent_type in ROBOTICS_INFO_RESPONSES:
        return ROBOTICS_INFO_RESPONSES[intent_type]
    if intent_type in ROBOTICS_CONVERSATIONAL_RESPONSES:
        responses = ROBOTICS_CONVERSATIONAL_RESPONSES[intent_type]
        if isinstance(responses, list):
            import random
            return random.choice(responses)
        return responses
    return None


def get_welcome_message() -> str:
    """Get welcome message template."""
    return ROBOTICS_WELCOME_MESSAGE


def get_error_response(error_type: str) -> str:
    """Get error response template."""
    return ROBOTICS_ERROR_RESPONSES.get(error_type, ROBOTICS_ERROR_RESPONSES['system_error'])

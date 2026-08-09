"""
Response Quality Validator
Validates LLM responses to ensure they match persona and quality standards
Can be enabled/disabled via ENABLE_RESPONSE_VALIDATION env variable
"""
import re
import os
from typing import Dict, Optional, List
from dotenv import load_dotenv

from tenant_config import get_tenant

load_dotenv()

# Configurable via .env
ENABLE_VALIDATION = os.getenv("ENABLE_RESPONSE_VALIDATION", "true").lower() == "true"


class ResponseValidator:
    """Validates and filters LLM responses"""

    # Persona leaks to rewrite regardless of tenant.
    BASE_REPLACEMENTS = {
        r'\b(as|as an)\s+an?\s+ai\s+(model|assistant)?\b': '',
        r'\bchatgpt\b': 'Chikku',
        r'\bai\s+model\b': 'assistant',
        r'\blanguage\s+model\b': 'assistant',
        r'\btrained\s+on\s+(a\s+)?dataset\b': '',
        r'\btraining\s+data\b': '',
        r'\bopenai\b': '',
        r'\bi\s+apologize\s+but\b': "I'm sorry",
        r'\bsorry\s+but\b': "I'm sorry",
    }

    # Restaurant tenant: rewrite RAG jargon into menu language.
    RESTAURANT_REPLACEMENTS = {
        r'\bartificial\s+intelligence\b': '',
        r'\bgoogle\b': '',
        r'\bretrieved\s+items?\b': 'menu items',
        r'\bcontext\s+(provided|given|above)\b': 'menu',
        r'\bbased\s+on\s+context\b': 'from our menu',
        r'\bcurrent\s+menu\s+context\b': 'our menu',
        r'\bprovided\s+context\b': 'menu',
    }

    # Company tenant: same jargon, neutral wording.
    GENERIC_REPLACEMENTS = {
        r'\bretrieved\s+items?\b': 'information',
        r'\bcontext\s+(provided|given|above)\b': 'information',
        r'\bbased\s+on\s+context\b': 'from our information',
        r'\bprovided\s+context\b': 'information',
    }


    def __init__(self, enabled: Optional[bool] = None):
        """
        Initialize validator
        
        Args:
            enabled: Override env variable. If None, uses ENABLE_RESPONSE_VALIDATION from .env
        """
        self.enabled = enabled if enabled is not None else ENABLE_VALIDATION
        self.tenant = get_tenant()

        # Phrases that should NEVER appear in responses
        self.forbidden_phrases = [
            r'\b(chatgpt|chat gpt)\b',
            r'\bai\s+model\b',
            r'\b(as|as an)\s+an?\s+ai\b',
            r'\blanguage\s+model\b',
            r'\bartificial\s+intelligence\b',
            r'\btrained\s+on\s+(a\s+)?dataset\b',
            r'\btraining\s+data\b',
            r'\bopenai\b',
            r'\bgoogle\b',
            r'\bdeep\s+learning\b',
            r'\bmachine\s+learning\b',
            r'\bneural\s+network\b',
            r'\bi\s+don\'t\s+have\s+(real-time\s+)?access\b',
            r'\bdeveloped\s+by\b',
            r'\bbased\s+on\s+language\s+models\b',
            r'\bi\'m\s+sorry\s+developed\b',
            r'\bthird-party\s+sources\b',
            r'\bexternal\s+systems\b',
            r'\bdatabase\s+access\b',
            r'\bdon\'t\s+have\s+access\s+to\s+current\s+events\b',
        ]
        
        # Technical jargon that breaks persona
        self.technical_jargon = [
            r'\bretrieved\s+items?\b',
            r'\bcontext\s+(provided|given|above)\b',
            r'\bbased\s+on\s+context\b',
            r'\bcurrent\s+menu\s+context\b',
            r'\bprovided\s+context\b',
            r'\bmetadata\b',
            r'\bretrieved_count\b',
            r'\bsystem\s+prompt\b',
            r'\bprevious\s+conversation\b',
        ]
        
        # Phrases that indicate uncertainty/apology (should be minimal)
        self.weak_phrases = [
            r'\bi\s+apologize\s+but\b',
            r'\bsorry\s+but\b',
            r'\bi\s+don\'t\s+have\s+access\b',
            r'\bi\s+can\'t\s+provide\b',
            r'\bas\s+an\s+ai\b',
        ]

        # Some tenants sell the very things the generic rules ban. Chikku
        # Robotics is an AI/robotics company, so "machine learning" and
        # "computer vision" are product vocabulary, not persona leaks.
        if self.tenant.validator_allow:
            self.forbidden_phrases = self._drop_allowed(self.forbidden_phrases)
            self.technical_jargon = self._drop_allowed(self.technical_jargon)
            self.weak_phrases = self._drop_allowed(self.weak_phrases)

        # Menu-specific rewrites only make sense for the restaurant tenant.
        self.replacements = dict(self.BASE_REPLACEMENTS)
        if self.tenant.is_restaurant:
            self.replacements.update(self.RESTAURANT_REPLACEMENTS)
        else:
            self.replacements.update(self.GENERIC_REPLACEMENTS)
        self.replacements = {
            pattern: repl
            for pattern, repl in self.replacements.items()
            if not self._is_allowed(pattern)
        }

    def _is_allowed(self, pattern: str) -> bool:
        """True if a rule targets a phrase this tenant is allowed to say."""
        plain = re.sub(r'\\[sb]\+?|\\b|[\\()?]', ' ', pattern)
        plain = re.sub(r'\s+', ' ', plain).strip().lower()
        return any(term in plain or plain in term for term in self.tenant.validator_allow)

    def _drop_allowed(self, patterns: List[str]) -> List[str]:
        return [p for p in patterns if not self._is_allowed(p)]
    
    def validate(self, response: str, query: str = "", context_provided: bool = False) -> Dict:
        """
        Validate response quality
        
        Args:
            response: The LLM-generated response
            query: Original user query (for context)
            context_provided: Whether menu context was provided
            
        Returns:
            Dict with:
                - valid: bool
                - score: float (0.0-1.0)
                - issues: List[str]
                - cleaned_response: str (if validation enabled)
        """
        if not self.enabled:
            return {
                "valid": True,
                "score": 1.0,
                "issues": [],
                "cleaned_response": response
            }
        
        response_lower = response.lower()
        issues = []
        score = 1.0
        
        # Check for forbidden phrases (critical issues)
        for pattern in self.forbidden_phrases:
            if re.search(pattern, response_lower, re.IGNORECASE):
                issues.append(f"Forbidden phrase detected: {pattern}")
                score -= 0.5  # Heavy penalty
        
        # Check for technical jargon
        for pattern in self.technical_jargon:
            if re.search(pattern, response_lower, re.IGNORECASE):
                issues.append(f"Technical jargon detected: {pattern}")
                score -= 0.2
        
        # Check for weak phrases
        for pattern in self.weak_phrases:
            if re.search(pattern, response_lower, re.IGNORECASE):
                issues.append(f"Weak phrase detected: {pattern}")
                score -= 0.1
        
        # Check response length
        if len(response.strip()) < 20:
            issues.append("Response too short")
            score -= 0.3
        
        # Check if response seems incomplete
        if response.strip().endswith('...') or response.strip().endswith('…'):
            issues.append("Response appears incomplete")
            score -= 0.1
        
        # Ensure score doesn't go below 0
        score = max(0.0, score)
        
        # Clean response if issues found
        cleaned_response = self._clean_response(response) if issues else response
        
        return {
            "valid": score >= 0.5,  # Valid if score >= 50%
            "score": score,
            "issues": issues,
            "cleaned_response": cleaned_response
        }
    
    def _clean_response(self, response: str) -> str:
        """
        Clean response by removing/rewriting problematic phrases
        
        Args:
            response: Original response
            
        Returns:
            Cleaned response
        """
        cleaned = response

        # Rule set is tenant-specific (see __init__).
        for pattern, replacement in self.replacements.items():
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        
        # Clean up multiple spaces
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = cleaned.strip()
        
        return cleaned
    
    def should_retry(self, validation_result: Dict) -> bool:
        """
        Determine if response should be regenerated
        
        Args:
            validation_result: Result from validate() method
            
        Returns:
            True if response should be retried
        """
        if not self.enabled:
            return False
        
        # Retry if score is too low or critical issues found
        return validation_result['score'] < 0.5 or len(validation_result['issues']) > 3


# Global validator instance
_validator_instance = None


def get_validator() -> ResponseValidator:
    """Get or create global validator instance"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = ResponseValidator()
    return _validator_instance

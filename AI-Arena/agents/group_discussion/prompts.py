"""
Prompt templates for Group Discussion Agent.
"""

def get_gd_analysis_prompt(content: str, topic: str) -> str:
    """Prompt for analyzing a group discussion transcript or notes."""
    return f"""I will provide you with two inputs:
- Content: Either unstructured notes or a transcript of a group discussion.
- Topic: The topic of the group discussion.

Your task is to process this and return a structured analysis in JSON format.

The analysis should help a participant or an HR admin evaluate the points and prepare for future interactions.

JSON Structure:
{{
    "structuredNotes": "A professional, organized version of the key points discussed, mapped to the topic.",
    "expectedResponses": ["List of possible counterpoints or follow-up questions other participants might raise."],
    "brainstormedStructure": "A clear roadmap (Opening, Key Pillars, Conclusion) to present these points effectively.",
    "sentiment": "Overall tone of the discussion (e.g., Collaborative, Competitive, Informative)",
    "key_takeaways": ["Bulleted list of core conclusions"]
}}

Return ONLY the JSON object.

Topic: {topic}
Content: {content}
"""

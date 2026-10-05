from azure.ai.textanalytics import TextAnalyticsClient, ExtractiveSummaryAction, AbstractiveSummaryAction
from azure.core.credentials import AzureKeyCredential
from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def analyze_sentiment(documents: list, credentials: dict = None):
    creds = credentials or {}
    endpoint = creds.get("AZURE_LANGUAGE_ENDPOINT") or settings.AZURE_LANGUAGE_ENDPOINT
    key = creds.get("AZURE_LANGUAGE_API_KEY") or settings.AZURE_LANGUAGE_API_KEY

    if not endpoint or not key:
        logger.error("Azure Language credentials missing")
        raise ValueError("Azure Language credentials are not configured. Please add them in your profile.")

    client = TextAnalyticsClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    try:
        response = client.analyze_sentiment(documents=documents)
        print("Rsponse" , response)
        results = []
        for idx, doc in enumerate(response):
            if not doc.is_error:
                results.append({
                    "id": idx,
                    "sentiment": doc.sentiment,
                    "confidence_scores": {
                        "positive": doc.confidence_scores.positive,
                        "neutral": doc.confidence_scores.neutral,
                        "negative": doc.confidence_scores.negative
                    },
                    "sentences": [
                        {
                            "text": s.text, 
                            "sentiment": s.sentiment, 
                            "confidence_scores": {
                                "positive": s.confidence_scores.positive,
                                "neutral": s.confidence_scores.neutral,
                                "negative": s.confidence_scores.negative
                            }
                        } for s in doc.sentences
                    ]
                })
            else:
                results.append({"id": idx, "error": doc.error.code, "message": doc.error.message})
        print(results)
        return results
    except Exception as e:
        logger.error(f"Error in Language service: {e}", exc_info=True)
        raise e

def extract_key_phrases(documents: list, credentials: dict = None):
    creds = credentials or {}
    endpoint = creds.get("AZURE_LANGUAGE_ENDPOINT") or settings.AZURE_LANGUAGE_ENDPOINT
    key = creds.get("AZURE_LANGUAGE_API_KEY") or settings.AZURE_LANGUAGE_API_KEY

    if not endpoint or not key:
        raise ValueError("Azure Language credentials are not configured.")

    client = TextAnalyticsClient(endpoint=endpoint, credential=AzureKeyCredential(key))
    try:
        response = client.extract_key_phrases(documents=documents)
        results = []
        for idx, doc in enumerate(response):
            if not doc.is_error:
                results.append({
                    "id": idx,
                    "key_phrases": doc.key_phrases
                })
            else:
                results.append({"id": idx, "error": doc.error.code, "message": doc.error.message})
        return results
    except Exception as e:
        logger.error(f"Error in Key Phrase extraction: {e}", exc_info=True)
        raise e

def recognize_entities(documents: list, credentials: dict = None):
    creds = credentials or {}
    endpoint = creds.get("AZURE_LANGUAGE_ENDPOINT") or settings.AZURE_LANGUAGE_ENDPOINT
    key = creds.get("AZURE_LANGUAGE_API_KEY") or settings.AZURE_LANGUAGE_API_KEY

    if not endpoint or not key:
        raise ValueError("Azure Language credentials are not configured.")

    client = TextAnalyticsClient(endpoint=endpoint, credential=AzureKeyCredential(key))
    try:
        response = client.recognize_entities(documents=documents)
        results = []
        for idx, doc in enumerate(response):
            if not doc.is_error:
                entities = [{"text": ent.text, "category": ent.category, "subcategory": ent.subcategory, "confidence": ent.confidence_score} for ent in doc.entities]
                results.append({
                    "id": idx,
                    "entities": entities
                })
            else:
                results.append({"id": idx, "error": doc.error.code, "message": doc.error.message})
        return results
    except Exception as e:
        logger.error(f"Error in Entity recognition: {e}", exc_info=True)
        raise e

def recognize_pii_entities(documents: list, credentials: dict = None):
    creds = credentials or {}
    endpoint = creds.get("AZURE_LANGUAGE_ENDPOINT") or settings.AZURE_LANGUAGE_ENDPOINT
    key = creds.get("AZURE_LANGUAGE_API_KEY") or settings.AZURE_LANGUAGE_API_KEY

    if not endpoint or not key:
        raise ValueError("Azure Language credentials are not configured.")

    client = TextAnalyticsClient(endpoint=endpoint, credential=AzureKeyCredential(key))
    try:
        response = client.recognize_pii_entities(documents=documents)
        results = []
        for idx, doc in enumerate(response):
            if not doc.is_error:
                entities = [{"text": ent.text, "category": ent.category, "confidence": ent.confidence_score} for ent in doc.entities]
                results.append({
                    "id": idx,
                    "pii_entities": entities,
                    "redacted_text": doc.redacted_text
                })
            else:
                results.append({"id": idx, "error": doc.error.code, "message": doc.error.message})
        return results
    except Exception as e:
        logger.error(f"Error in PII recognition: {e}", exc_info=True)
        raise e

def detect_language(documents: list, credentials: dict = None):
    creds = credentials or {}
    endpoint = creds.get("AZURE_LANGUAGE_ENDPOINT") or settings.AZURE_LANGUAGE_ENDPOINT
    key = creds.get("AZURE_LANGUAGE_API_KEY") or settings.AZURE_LANGUAGE_API_KEY

    if not endpoint or not key:
        raise ValueError("Azure Language credentials are not configured.")

    client = TextAnalyticsClient(endpoint=endpoint, credential=AzureKeyCredential(key))
    try:
        # detect_language expects a list of dictionaries usually if passing id/text, or just list of strings
        # docs say: "InputStr" or "DetectLanguageInput"
        # Since we are passing just text list in other functions, let's assume simple implementation or wrap it
        # However, detect_language takes `documents` (list of strings or dicts).
        response = client.detect_language(documents=documents)
        results = []
        for idx, doc in enumerate(response):
            if not doc.is_error:
                results.append({
                    "id": idx,
                    "primary_language": {
                        "name": doc.primary_language.name,
                        "iso6391_name": doc.primary_language.iso6391_name,
                        "confidence_score": doc.primary_language.confidence_score
                    }
                })
            else:
                results.append({"id": idx, "error": doc.error.code, "message": doc.error.message})
        return results
    except Exception as e:
        logger.error(f"Error in Language detection: {e}", exc_info=True)
        raise e

def summarize_text(documents: list, credentials: dict = None):
    creds = credentials or {}
    endpoint = creds.get("AZURE_LANGUAGE_ENDPOINT") or settings.AZURE_LANGUAGE_ENDPOINT
    key = creds.get("AZURE_LANGUAGE_API_KEY") or settings.AZURE_LANGUAGE_API_KEY

    if not endpoint or not key:
        raise ValueError("Azure Language credentials are not configured.")

    client = TextAnalyticsClient(endpoint=endpoint, credential=AzureKeyCredential(key))
    try:
        poller = client.begin_analyze_actions(
            documents,
            actions=[ExtractiveSummaryAction(max_sentence_count=3)]
        )
        document_results = poller.result()
        
        results = []
        for action_result_page in document_results:
            for result in action_result_page:

                if result.is_error:
                    results.append({
                        "id": result.id,
                        "error": result.error.code,
                        "message": result.error.message
                    })
                else:
                    sentences = [
                        {"text": s.text, "rank_score": s.rank_score}
                        for s in result.sentences
                    ]

                    results.append({
                        "id": result.id,
                        "summary_sentences": sentences
                    }) 
        # If results are empty but no exception, it might be due to structure.
        # But this basic iteration should work for single action.
        return results
    except Exception as e:
        logger.error(f"Error in Summarization: {e}", exc_info=True)
        raise e

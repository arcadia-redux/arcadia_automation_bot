import os
from google.cloud.translate import TranslationServiceAsyncClient
from typing import List, Optional

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = os.getcwd() + f"/bot/{os.getenv('GOOGLE_PROJECT_CREDS_FILENAME', '')}"

client = TranslationServiceAsyncClient()
parent = f"projects/{os.getenv('GOOGLE_PROJECT_API', '')}/locations/global"


async def translate_single(input_text: str, target_lang: Optional[str] = "en-US"):
    translations = await translate([input_text, ], target_lang)
    result = translations[0]
    return result.translated_text, result.detected_language_code


async def translate(input_strings: List[str], target_lang: Optional[str] = "en-US"):
    response = await client.translate_text(
        request={
            "parent": parent,
            "contents": input_strings,
            "mime_type": "text/plain",
            "target_language_code": target_lang,
        }
    )
    return response.translations

